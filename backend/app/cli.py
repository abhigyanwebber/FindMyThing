"""Operator CLI: `python -m app.cli <command>` (contract A11, A16). Run from `backend/` with DATABASE_URL set.

Commands:
  create-moderator              interactive provisioning (name, email, hidden password prompt; never updates accounts)
  seed-reference-data           idempotent campus seed from a validated config file
  cleanup-retention             run the retention executor (add --dry-run to only count)
  matching-jobs list|retry|run  inspect DEAD jobs, requeue one, or process due jobs via the existing outbox worker

Exit codes: 0 success, 1 operational failure or partial failure, 2 invalid input or configuration.
Output contains counts and stable codes only: no passwords, Blob keys, evidence or SQL text.
"""

from __future__ import annotations

import argparse
import getpass
import logging
import sys
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings, load_campus_config
from app.core.errors import AppError
from app.core.text import clean_text, normalize_email, validate_password
from app.persistence.database import session_scope
from app.services import cleanup, operator

EXIT_OK, EXIT_FAILURE, EXIT_USAGE = 0, 1, 2
PASSWORD_ATTEMPTS = 3

Prompt = Callable[[str], str]


def _uuid_arg(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a UUID") from None


def _positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a whole number") from None
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="FindMyThing operator maintenance commands.")
    commands = parser.add_subparsers(dest="command", required=True, metavar="<command>")

    commands.add_parser("create-moderator", help="Create a moderator account (interactive; refuses an existing email).")

    seed = commands.add_parser("seed-reference-data", help="Idempotently seed roles, categories, zones and locations.")
    seed.add_argument("--config", metavar="PATH", help="Campus config JSON (default: CAMPUS_CONFIG_PATH, i.e. config/campus.json).")

    clean = commands.add_parser("cleanup-retention", help="Purge expired photos/evidence, orphan Blobs and old activity logs.")
    clean.add_argument("--dry-run", action="store_true", help="Only count what would be removed; change nothing and write no audit event.")

    jobs = commands.add_parser("matching-jobs", help="Matching outbox maintenance.")
    job_cmds = jobs.add_subparsers(dest="jobs_command", required=True, metavar="<action>")
    listing = job_cmds.add_parser("list", help="List matching jobs by status (default DEAD).")
    listing.add_argument("--status", choices=operator.JOB_STATUSES, default="DEAD")
    listing.add_argument("--limit", type=_positive_int, default=100, help="Maximum rows to show (default 100).")
    retry = job_cmds.add_parser("retry", help="Requeue one DEAD job (resets attempts; audited as OPERATOR).")
    retry.add_argument("job_id", type=_uuid_arg)
    run = job_cmds.add_parser("run", help="Process due jobs now through the existing outbox worker.")
    run.add_argument("--max-jobs", type=_positive_int, default=100, help="Stop after this many jobs (default 100).")
    return parser


def _err(message: str) -> None:
    print(message, file=sys.stderr)


# ------------------------------------------------------------------------------ create-moderator

def _read_password(secret: Prompt) -> str | None:
    for _ in range(PASSWORD_ATTEMPTS):
        password = secret("Password (hidden): ")
        try:
            validate_password(password)
        except AppError as exc:
            _err("; ".join((exc.field_errors or {}).get("password", [exc.message])))
            continue
        if secret("Confirm password: ") != password:
            _err("Passwords do not match.")
            continue
        return password
    return None


def _cmd_create_moderator(prompt: Prompt, secret: Prompt) -> int:
    try:  # validate the non-secret fields first so a typo never costs a typed password
        name = clean_text(prompt("Display name: "), field="display_name", min_len=1, max_len=80)
        email = normalize_email(prompt("Email: "))
    except AppError as exc:
        _err(f"Invalid input: {exc.message} {exc.field_errors or ''}".strip())
        return EXIT_USAGE
    password = _read_password(secret)
    if password is None:
        _err("No valid password was entered. Nothing was created.")
        return EXIT_USAGE
    try:
        with session_scope() as db:
            user = operator.create_moderator(
                db, display_name=name, email=email, password=password, correlation_id=f"cli-{uuid.uuid4()}"
            )
            user_id = user.user_id
    except operator.OperatorError as exc:
        _err(f"Refused ({exc.code}): {exc.message}")
        return EXIT_FAILURE
    except AppError as exc:
        _err(f"Invalid input: {exc.message} {exc.field_errors or ''}".strip())
        return EXIT_USAGE
    print(f"Moderator created: {email} (user id {user_id}).")
    return EXIT_OK


# ------------------------------------------------------------------------------ seed-reference-data

def _cmd_seed(config: str | None) -> int:
    path = Path(config) if config else get_settings().campus_config_file()
    try:
        campus = load_campus_config(path)
    except FileNotFoundError as exc:
        _err(str(exc))
        return EXIT_USAGE
    except (ValueError, KeyError, TypeError) as exc:  # JSON syntax, missing keys, bad timezone, duplicates, unknown zone
        _err(f"Invalid campus config: {exc}")
        return EXIT_USAGE
    try:
        with session_scope() as db:  # one transaction: a failure leaves the database exactly as it was
            result = operator.seed_campus(db, campus)
    except operator.OperatorError as exc:
        _err(f"Refused ({exc.code}): {exc.message}")
        return EXIT_USAGE
    except SQLAlchemyError as exc:
        _err(f"Seeding failed and was rolled back; nothing was changed ({type(exc).__name__}). "
             "Check for names that already exist under a different slug.")
        return EXIT_FAILURE
    created = ", ".join(f"{k}={v}" for k, v in result.created.items())
    print(f"Reference data seeded from {path.name}: created {created}.")
    if sum(result.created.values()) == 0:
        print("Nothing to create: reference data was already up to date.")
    if result.differing:
        print(f"WARNING: {len(result.differing)} existing row(s) differ from the config and were NOT renamed "
              f"(a name or zone change needs a reviewed migration): {', '.join(result.differing)}")
    return EXIT_OK


# ------------------------------------------------------------------------------ cleanup-retention

def _cmd_cleanup(dry_run: bool) -> int:
    s = cleanup.run_retention_cleanup(dry_run=dry_run)
    print("Retention cleanup" + (" (DRY RUN: nothing was changed)" if dry_run else ""))
    print(f"  Report photos:  eligible={s.attachments_eligible} purged={s.attachments_purged} "
          f"deferred={s.attachments_deferred} failed={s.attachments_failed}")
    print(f"  Claim evidence: eligible={s.evidence_eligible} purged={s.evidence_purged} "
          f"deferred={s.evidence_deferred} failed={s.evidence_failed}")
    print(f"  Orphan Blobs:   scanned={s.orphan_blobs_scanned} eligible={s.orphan_blobs_eligible} "
          f"removed={s.orphan_blobs_removed} failed={s.orphan_blobs_failed} not_ours_ignored={s.foreign_blobs_ignored}")
    print(f"  Activity logs:  eligible={s.activity_logs_eligible} purged={s.activity_logs_purged}")
    if s.phase_errors:
        print(f"  Problems: {', '.join(s.phase_errors)}")
    if not dry_run:
        print("  Audit event: " + ("recorded" if s.audit_recorded else "NOT recorded"))
    if s.failures:
        _err(f"Cleanup finished with {s.failures} failure(s); affected items keep their data and are retried on the next run.")
    return EXIT_OK if s.ok else EXIT_FAILURE


# ------------------------------------------------------------------------------ matching-jobs

def _cmd_jobs_list(status: str, limit: int) -> int:
    try:
        with session_scope() as db:
            rows, total = operator.list_jobs(db, status, limit)
    except operator.OperatorError as exc:
        _err(f"Refused ({exc.code}): {exc.message}")
        return EXIT_USAGE
    print(f"{total} {status} matching job(s)" + (f" (showing {len(rows)})" if total > len(rows) else ""))
    for j in rows:
        updated = j.updated_at_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        print(f"  {j.job_id}  report={j.report_id}  v{j.matching_version}  attempts={j.attempt_count}  "
              f"error={j.last_error_code or '-'}  updated={updated}")
    if status == "DEAD" and rows:
        print("Retry one with: python -m app.cli matching-jobs retry <job_id>")
    return EXIT_OK


def _cmd_jobs_retry(job_id: uuid.UUID) -> int:
    try:
        with session_scope() as db:
            row = operator.retry_job(db, job_id, f"cli-{uuid.uuid4()}")
    except operator.OperatorError as exc:
        _err(f"Refused ({exc.code}): {exc.message}")
        return EXIT_FAILURE
    print(f"Job {row.job_id} requeued as {row.status} (attempts reset to {row.attempt_count}); it will run on the next worker pass.")
    return EXIT_OK


def _cmd_jobs_run(max_jobs: int) -> int:
    r = operator.run_matching_jobs(max_jobs)
    print(f"Matching run: processed={r.processed} succeeded={r.succeeded} superseded={r.superseded} skipped={r.skipped} "
          f"failed_retry_scheduled={r.failed_retry_scheduled} failed_dead={r.failed_dead}")
    for label, q in (("Queue before", r.before), ("Queue after ", r.after)):
        print(f"  {label}: due={q.pending_due} backoff={q.pending_backoff} leased={q.processing_active} "
              f"stale_reclaimable={q.processing_stale} dead={q.dead}")
    if r.limit_reached:
        print(f"  Stopped at --max-jobs={max_jobs}; run again to continue.")
    if r.after.dead:
        print(f"  {r.after.dead} DEAD job(s) need attention: python -m app.cli matching-jobs list --status DEAD")
    return EXIT_FAILURE if r.failed_dead else EXIT_OK


# ------------------------------------------------------------------------------ entry point

def main(argv: Sequence[str] | None = None, *, prompt: Prompt = input, secret: Prompt = getpass.getpass) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        match args.command:
            case "create-moderator":
                return _cmd_create_moderator(prompt, secret)
            case "seed-reference-data":
                return _cmd_seed(args.config)
            case "cleanup-retention":
                return _cmd_cleanup(args.dry_run)
            case "matching-jobs":
                match args.jobs_command:
                    case "list":
                        return _cmd_jobs_list(args.status, args.limit)
                    case "retry":
                        return _cmd_jobs_retry(args.job_id)
                    case _:
                        return _cmd_jobs_run(args.max_jobs)
    except SQLAlchemyError as exc:  # never print str(exc): SQLAlchemy messages embed statements and bound parameters
        _err(f"The database is unavailable or misconfigured ({type(exc).__name__}). Check DATABASE_URL and that SQL Server is running.")
        return EXIT_FAILURE
    except RuntimeError as exc:  # e.g. DATABASE_URL is not configured (our own message)
        _err(str(exc))
        return EXIT_FAILURE
    return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
