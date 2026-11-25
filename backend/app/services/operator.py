"""Operator maintenance services behind `python -m app.cli` (contract A11, A16).

Nothing here is reachable from the public API. Every function takes a Session and leaves commit/rollback to the
caller (`session_scope`), so each operator action is one transaction with its audit record.

Matching jobs reuse the existing worker (`lease_next_job` / `process_job`): leasing, READPAST concurrency safety,
exponential backoff, stale-lease reclaim and DEAD marking all stay in `matching_worker`. This module adds no
second matching implementation.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections import Counter
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import hash_password, new_id, seed_id, utcnow
from app.core.text import clean_text, normalize_email, validate_password
from app.persistence.database import get_sessionmaker
from app.persistence.models import Category, Location, MatchingJob, Role, User
from app.services import audit
from app.services.matching_worker import lease_next_job, process_job
from app.services.seed import moderator_role_id, seed_reference_data

OPERATOR = "OPERATOR"
JOB_STATUSES = ("PENDING", "PROCESSING", "SUCCEEDED", "SUPERSEDED", "DEAD")


class OperatorError(Exception):
    """A refused or failed operator action with a stable code and a message that is safe to print."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ------------------------------------------------------------------------------ create-moderator

def create_moderator(db: Session, *, display_name: str, email: str, password: str, correlation_id: str) -> User:
    """Provision a MODERATOR (contract A16, D-023). Never updates an existing account; no default password.

    Raises AppError (422) for invalid input and OperatorError for an existing email or unseeded roles.
    The password is hashed with the project's Argon2id hasher and is never logged, audited or returned.
    """
    name = clean_text(display_name, field="display_name", min_len=1, max_len=80)
    normalized = normalize_email(email)
    validate_password(password)
    if db.get(Role, moderator_role_id()) is None:
        raise OperatorError("REFERENCE_DATA_MISSING", "Roles are not seeded yet. Run `seed-reference-data` first.")
    if db.scalar(select(User.user_id).where(User.email_normalized == normalized)) is not None:
        raise OperatorError("EMAIL_EXISTS", "An account with this email already exists. Nothing was changed.")
    now = utcnow()
    user = User(
        user_id=new_id(), role_id=moderator_role_id(), display_name=name, email_normalized=normalized,
        password_hash=hash_password(password), is_active=True, created_at_utc=now, updated_at_utc=now,
    )
    try:
        with db.begin_nested():  # a concurrent insert of the same email loses cleanly on the unique index
            db.add(user)
            db.flush()
    except IntegrityError:
        raise OperatorError("EMAIL_EXISTS", "An account with this email already exists. Nothing was changed.") from None
    # The frozen event taxonomy has no dedicated event, so the account-creation event is reused; `role` and
    # `operator` in the allowlisted metadata distinguish it from a public student registration.
    audit.log_event(
        db, event_type="AUTH_REGISTERED", outcome="SUCCESS", correlation_id=correlation_id, actor_user_id=None,
        target_type="USER", target_id=user.user_id, metadata={"role": "MODERATOR", "operator": OPERATOR},
    )
    return user


# ------------------------------------------------------------------------------ seed-reference-data

@dataclass(frozen=True)
class SeedResult:
    created: dict[str, int]
    differing: list[str]  # "kind:slug" rows that exist under a different name/zone than the config; never renamed


def _check_slug_collisions(campus: dict) -> None:
    zone_slugs = {z["slug"] for z in campus["zones"]}
    clash = sorted(zone_slugs & {loc["slug"] for loc in campus["locations"]})
    if clash:  # zones and locations share one UUIDv5 namespace ("location"), so a shared slug would silently collide
        raise OperatorError("SLUG_COLLISION", f"A slug is used by both a zone and a location: {', '.join(clash)}")


def seed_campus(db: Session, campus: dict) -> SeedResult:
    """Idempotent seed in the caller's single transaction (all-or-nothing). Existing rows are never renamed."""
    _check_slug_collisions(campus)
    created = seed_reference_data(db, campus)
    differing: list[str] = []
    for c in campus["categories"]:
        row = db.get(Category, seed_id("category", c["slug"]))
        if row is not None and row.name != c["name"]:
            differing.append(f"category:{c['slug']}")
    for z in campus["zones"]:
        zrow = db.get(Location, seed_id("location", z["slug"]))
        if zrow is not None and zrow.name != z["name"]:
            differing.append(f"zone:{z['slug']}")
    for loc in campus["locations"]:
        lrow = db.get(Location, seed_id("location", loc["slug"]))
        if lrow is not None and (lrow.name != loc["name"] or lrow.zone_id != seed_id("location", loc["zone_slug"])):
            differing.append(f"location:{loc['slug']}")
    return SeedResult(created=created, differing=differing)


# ------------------------------------------------------------------------------ matching-jobs

@dataclass(frozen=True)
class JobRow:
    job_id: uuid.UUID
    report_id: uuid.UUID
    matching_version: int
    status: str
    attempt_count: int
    last_error_code: str | None
    next_attempt_at_utc: dt.datetime | None
    updated_at_utc: dt.datetime


@dataclass(frozen=True)
class QueueStats:
    pending_due: int
    pending_backoff: int  # PENDING but waiting for its retry delay
    processing_active: int  # leased and the lease is still valid
    processing_stale: int  # lease expired: the next worker reclaims it
    dead: int


@dataclass(frozen=True)
class MatchingRunSummary:
    before: QueueStats
    after: QueueStats
    processed: int
    succeeded: int
    superseded: int
    skipped: int
    failed_retry_scheduled: int
    failed_dead: int
    limit_reached: bool


def list_jobs(db: Session, status: str = "DEAD", limit: int = 100) -> tuple[list[JobRow], int]:
    """Jobs in a status, most recently updated first. Reports ids only: no titles, descriptions or user data."""
    if status not in JOB_STATUSES:
        raise OperatorError("INVALID_STATUS", f"Status must be one of: {', '.join(JOB_STATUSES)}.")
    total = int(db.scalar(select(func.count()).select_from(MatchingJob).where(MatchingJob.status == status)) or 0)
    rows = db.scalars(
        select(MatchingJob).where(MatchingJob.status == status)
        .order_by(MatchingJob.updated_at_utc.desc(), MatchingJob.job_id).limit(limit)
    ).all()
    return [
        JobRow(j.job_id, j.report_id, j.report_matching_version, j.status, j.attempt_count, j.last_error_code,
               j.next_attempt_at_utc, j.updated_at_utc)
        for j in rows
    ], total


def retry_job(db: Session, job_id: uuid.UUID, correlation_id: str) -> JobRow:
    """Requeue one DEAD job on its existing idempotency-key row (contract A11). Never touches report/claim status."""
    job = db.execute(
        select(MatchingJob).where(MatchingJob.job_id == job_id).with_hint(MatchingJob, "WITH (UPDLOCK, HOLDLOCK)", "mssql")
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if job is None:
        raise OperatorError("JOB_NOT_FOUND", "No matching job with that id.")
    if job.status != "DEAD":
        raise OperatorError("JOB_NOT_DEAD", f"The job is {job.status}; only DEAD jobs can be retried.")
    previous_attempts, previous_error = job.attempt_count, job.last_error_code
    now = utcnow()
    job.status, job.attempt_count, job.next_attempt_at_utc = "PENDING", 0, now
    job.lease_expires_at_utc, job.last_error_code, job.updated_at_utc = None, None, now
    db.flush()
    audit.log_event(
        db, event_type="MATCH_JOB_RETRIED", outcome="SUCCESS", correlation_id=correlation_id, actor_user_id=None,
        target_type="REPORT", target_id=job.report_id,
        metadata={"job_id": job.job_id, "attempt_count": previous_attempts, "error_code": previous_error, "operator": OPERATOR},
    )
    return JobRow(job.job_id, job.report_id, job.report_matching_version, job.status, job.attempt_count,
                  job.last_error_code, job.next_attempt_at_utc, job.updated_at_utc)


def queue_stats(db: Session, now: dt.datetime | None = None) -> QueueStats:
    now = now or utcnow()

    def count(*conditions) -> int:
        return int(db.scalar(select(func.count()).select_from(MatchingJob).where(*conditions)) or 0)

    return QueueStats(
        pending_due=count(MatchingJob.status == "PENDING", MatchingJob.next_attempt_at_utc <= now),
        pending_backoff=count(MatchingJob.status == "PENDING", MatchingJob.next_attempt_at_utc > now),
        processing_active=count(MatchingJob.status == "PROCESSING", MatchingJob.lease_expires_at_utc > now),
        processing_stale=count(MatchingJob.status == "PROCESSING", MatchingJob.lease_expires_at_utc <= now),
        dead=count(MatchingJob.status == "DEAD"),
    )


def run_matching_jobs(max_jobs: int = 100) -> MatchingRunSummary:
    """Process due work through the existing outbox worker: lease -> score -> write, with its retry/backoff/DEAD rules.

    Safe next to the API poller and other CLI runs: `lease_next_job` uses READPAST row leases. Stale PROCESSING
    leases are reclaimed by the same lease query; jobs still in backoff and DEAD jobs are left alone.
    """
    sessions = get_sessionmaker()
    with sessions() as db:
        before = queue_stats(db)
    outcomes: Counter[str] = Counter()
    processed = 0
    while processed < max_jobs:
        with sessions() as db:
            job_id = lease_next_job(db)
        if job_id is None:
            break
        outcomes[process_job(job_id)] += 1
        processed += 1
    with sessions() as db:
        after = queue_stats(db)
    return MatchingRunSummary(
        before=before, after=after, processed=processed, succeeded=outcomes["SUCCEEDED"],
        superseded=outcomes["SUPERSEDED"], skipped=outcomes["SKIPPED"], failed_retry_scheduled=outcomes["PENDING"],
        failed_dead=outcomes["DEAD"], limit_reached=processed >= max_jobs,
    )
