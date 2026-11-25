"""Operator CLI (contract A11, A16): `python -m app.cli`. Real SQL Server; prompts are scripted, never a real terminal.

`cli.main(argv, prompt=..., secret=...)` is the production entry point with its two input functions injected, so these
tests drive exactly the code path the console script runs. The CLI opens its own sessions (like production), so test data
is always committed before a command runs.
"""

from __future__ import annotations

import copy
import datetime as dt
import getpass
import json
import re
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.exc import OperationalError

from app import cli
from app.core.config import get_campus_config
from app.core.security import seed_id, utcnow, verify_password
from app.persistence.database import get_sessionmaker
from app.persistence.models import ActivityLog, Category, Location, Match, MatchingJob, Report, Role, User
from app.services import matching_worker
from app.services.blobstore import LocalBlobStore, set_blob_store
from app.services.matching_state import enqueue_job
from app.services.seed import moderator_role_id, seed_reference_data, student_role_id
from tests.helpers import make_report, make_user
from tests.test_retention_cleanup import (
    SECRET_FILENAME,
    FlakyStore,
    att_state,
    ev_state,
    evidence,
    has_blob,
    photo,
    terminal_claim,
    terminal_report,
)

pytestmark = pytest.mark.sql

PW = "a-long-unique-passphrase-9"
EXAMPLE_CONFIG = Path(__file__).resolve().parents[2] / "config" / "campus.example.json"
ORIGIN = "http://localhost:5173"


class Script:
    """Scripted stand-in for input()/getpass(). Asking more often than scripted fails the test loudly."""

    def __init__(self, *answers: str) -> None:
        self.answers = list(answers)
        self.asked: list[str] = []

    def __call__(self, text: str) -> str:
        self.asked.append(text)
        return self.answers.pop(0)


def run_cli(argv, *, prompt: Script | None = None, secret: Script | None = None) -> int:
    return cli.main(argv, prompt=prompt or Script(), secret=secret or Script())


def count(db, model) -> int:
    db.expire_all()
    return int(db.scalar(select(func.count()).select_from(model)) or 0)


@pytest.fixture()
def cli_store(tmp_path):
    s = LocalBlobStore(str(tmp_path / "cli-blobs"))
    set_blob_store(s)
    yield s
    set_blob_store(None)


@pytest.fixture()
def flaky_store(tmp_path):
    s = FlakyStore(str(tmp_path / "cli-flaky"))
    set_blob_store(s)
    yield s
    set_blob_store(None)


@pytest.fixture()
def blank_reference_data(db):
    """Empty categories/locations (no report references them in a fresh test) and restore the shared test campus after."""
    campus = copy.deepcopy(get_campus_config())

    def wipe() -> None:
        with get_sessionmaker()() as s:
            s.execute(delete(Location).where(Location.is_zone == False))  # T-SQL needs `== False`; `.is_(False)` emits `IS 0`
            s.execute(delete(Location))
            s.execute(delete(Category))
            s.commit()

    wipe()
    yield
    wipe()
    with get_sessionmaker()() as s:
        seed_reference_data(s, campus)
        s.commit()


# ------------------------------------------------------------------------------------ registration and argument validation

def test_every_command_is_registered_and_has_help(capsys):
    for argv in (["--help"], ["create-moderator", "--help"], ["seed-reference-data", "--help"], ["cleanup-retention", "--help"],
                 ["matching-jobs", "--help"], ["matching-jobs", "list", "--help"], ["matching-jobs", "retry", "--help"],
                 ["matching-jobs", "run", "--help"]):
        with pytest.raises(SystemExit) as exc:
            cli.main(argv)
        assert exc.value.code == 0
    help_text = capsys.readouterr().out
    for name in ("create-moderator", "seed-reference-data", "cleanup-retention", "matching-jobs"):
        assert name in help_text


@pytest.mark.parametrize("argv", [
    [], ["bogus-command"], ["matching-jobs"], ["matching-jobs", "bogus"], ["matching-jobs", "retry"],
    ["matching-jobs", "retry", "not-a-uuid"], ["matching-jobs", "run", "--max-jobs", "0"],
    ["matching-jobs", "run", "--max-jobs", "-3"], ["matching-jobs", "run", "--max-jobs", "many"],
    ["matching-jobs", "list", "--limit", "0"], ["matching-jobs", "list", "--status", "NOT_A_STATUS"],
    ["cleanup-retention", "--force"], ["seed-reference-data", "--no-such-flag"],
])
def test_invalid_arguments_are_rejected_with_exit_code_2(argv):
    with pytest.raises(SystemExit) as exc:
        cli.main(argv)
    assert exc.value.code == cli.EXIT_USAGE


def test_valid_arguments_parse_to_the_expected_values():
    parser = cli.build_parser()
    job_id = uuid.uuid4()
    assert parser.parse_args(["matching-jobs", "retry", str(job_id)]).job_id == job_id
    run_args = parser.parse_args(["matching-jobs", "run"])
    assert (run_args.command, run_args.jobs_command, run_args.max_jobs) == ("matching-jobs", "run", 100)
    listing = parser.parse_args(["matching-jobs", "list"])
    assert (listing.status, listing.limit) == ("DEAD", 100)
    assert parser.parse_args(["cleanup-retention", "--dry-run"]).dry_run is True
    assert parser.parse_args(["cleanup-retention"]).dry_run is False


# ------------------------------------------------------------------------------------ create-moderator

def test_create_moderator_provisions_an_argon2id_moderator_and_audits_it(db, capsys):
    code = run_cli(["create-moderator"], prompt=Script("  Mona   Moderator ", " Mona@Campus.EDU "), secret=Script(PW, PW))
    out = capsys.readouterr()
    assert code == cli.EXIT_OK
    db.expire_all()
    user = db.scalars(select(User)).one()
    assert (user.email_normalized, user.display_name) == ("mona@campus.edu", "Mona Moderator")
    assert user.role_id == moderator_role_id() and user.is_active
    assert user.password_hash.startswith("$argon2id$") and PW not in user.password_hash
    assert verify_password(user.password_hash, PW) and not verify_password(user.password_hash, PW + "x")
    event = db.scalars(select(ActivityLog).where(ActivityLog.event_type == "AUTH_REGISTERED")).one()
    assert event.actor_user_id is None and event.target_id == user.user_id and event.outcome == "SUCCESS"
    assert json.loads(event.metadata_json) == {"role": "MODERATOR", "operator": "OPERATOR"}
    assert PW not in out.out + out.err + (event.metadata_json or "")


def test_the_password_is_read_with_the_hidden_prompt_by_default():
    assert cli.main.__kwdefaults__["secret"] is getpass.getpass


def test_there_is_no_way_to_pass_or_default_a_password():
    with pytest.raises(SystemExit) as exc:
        cli.main(["create-moderator", "--password", "x"])
    assert exc.value.code == cli.EXIT_USAGE
    assert not any(opt in cli.build_parser().format_help() for opt in ("--password", "--email"))


def test_create_moderator_refuses_an_existing_moderator_email(db, capsys):
    run_cli(["create-moderator"], prompt=Script("Mona", "mona@campus.edu"), secret=Script(PW, PW))
    capsys.readouterr()
    code = run_cli(["create-moderator"], prompt=Script("Other Name", "MONA@campus.edu "), secret=Script("another-long-secret-1", "another-long-secret-1"))
    assert code == cli.EXIT_FAILURE and "EMAIL_EXISTS" in capsys.readouterr().err
    db.expire_all()
    user = db.scalars(select(User)).one()
    assert user.display_name == "Mona" and verify_password(user.password_hash, PW)
    assert count(db, ActivityLog) == 1  # only the first creation was audited


def test_create_moderator_never_promotes_or_changes_an_existing_student(db, capsys):
    student = make_user(db, "STUDENT", "Sam Student", "sam@campus.edu")
    before = (student.user_id, student.role_id, student.display_name, student.password_hash, student.is_active)
    db.commit()
    code = run_cli(["create-moderator"], prompt=Script("Evil Admin", " SAM@campus.edu"), secret=Script(PW, PW))
    assert code == cli.EXIT_FAILURE and "EMAIL_EXISTS" in capsys.readouterr().err
    db.expire_all()
    row = db.scalars(select(User)).one()
    assert (row.user_id, row.role_id, row.display_name, row.password_hash, row.is_active) == before
    assert row.role_id == student_role_id() and count(db, ActivityLog) == 0


@pytest.mark.parametrize(("name", "email"), [("", "a@campus.edu"), ("   ", "a@campus.edu"), ("x" * 81, "a@campus.edu"),
                                             ("Ok Name", "not-an-email"), ("Ok Name", "a..b@campus.edu"), ("Ok Name", "")])
def test_bad_name_or_email_is_rejected_before_any_password_is_requested(db, capsys, name, email):
    secret = Script()
    assert run_cli(["create-moderator"], prompt=Script(name, email), secret=secret) == cli.EXIT_USAGE
    assert secret.asked == [] and count(db, User) == 0
    assert "Invalid input" in capsys.readouterr().err


@pytest.mark.parametrize("answers", [
    ("short", "short", "short"),  # under 12 characters, three times
    (" " * 14, " " * 14, " " * 14),  # whitespace only
    (PW, "x" * 14, PW, "y" * 14, PW, "z" * 14),  # confirmation never matches
])
def test_three_unusable_password_attempts_create_nothing(db, capsys, answers):
    code = run_cli(["create-moderator"], prompt=Script("Mona", "mona@campus.edu"), secret=Script(*answers))
    out = capsys.readouterr()
    assert code == cli.EXIT_USAGE and count(db, User) == 0 and count(db, ActivityLog) == 0
    assert PW not in out.out + out.err


def test_a_valid_password_after_a_rejected_one_is_accepted(db):
    code = run_cli(["create-moderator"], prompt=Script("Mona", "mona@campus.edu"), secret=Script("short", PW, PW))
    assert code == cli.EXIT_OK and count(db, User) == 1


def test_create_moderator_needs_seeded_roles_and_changes_nothing_without_them(db, capsys):
    campus = copy.deepcopy(get_campus_config())
    with get_sessionmaker()() as s:
        s.execute(delete(Role).where(Role.role_id == moderator_role_id()))
        s.commit()
    try:
        code = run_cli(["create-moderator"], prompt=Script("Mona", "mona@campus.edu"), secret=Script(PW, PW))
        assert code == cli.EXIT_FAILURE and "REFERENCE_DATA_MISSING" in capsys.readouterr().err
        assert count(db, User) == 0
    finally:
        with get_sessionmaker()() as s:
            seed_reference_data(s, campus)
            s.commit()


def test_public_registration_cannot_create_a_moderator(db):
    from app.main import create_app

    with TestClient(create_app(), headers={"Origin": ORIGIN}) as client:
        smuggled = client.post("/api/auth/register", json={"display_name": "Eve", "email": "eve@campus.edu", "password": PW,
                                                           "role": "MODERATOR"})
        assert smuggled.status_code == 422
        assert client.post("/api/auth/register", json={"display_name": "Eve", "email": "eve@campus.edu", "password": PW}).status_code == 201
    db.expire_all()
    assert db.scalars(select(User)).one().role_id == student_role_id()


# ------------------------------------------------------------------------------------ seed-reference-data

def write_config(tmp_path: Path, data) -> str:
    path = tmp_path / "campus.json"
    path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
    return str(path)


def reference_counts(db) -> tuple[int, int, int]:
    return count(db, Role), count(db, Category), count(db, Location)


def test_seed_populates_the_campus_config_and_repeating_it_creates_nothing(blank_reference_data, db, capsys):
    campus = json.loads(EXAMPLE_CONFIG.read_text(encoding="utf-8"))
    assert run_cli(["seed-reference-data", "--config", str(EXAMPLE_CONFIG)]) == cli.EXIT_OK
    first = capsys.readouterr().out
    expected = f"categories={len(campus['categories'])}, zones={len(campus['zones'])}, locations={len(campus['locations'])}"
    assert expected in first

    db.expire_all()
    assert {c.slug: c.name for c in db.scalars(select(Category))} == {c["slug"]: c["name"] for c in campus["categories"]}
    assert all(c.is_active and c.category_id == seed_id("category", c.slug) for c in db.scalars(select(Category)))
    rows = {loc.slug: loc for loc in db.scalars(select(Location))}
    assert {s for s, loc in rows.items() if loc.is_zone} == {z["slug"] for z in campus["zones"]}
    for zone in campus["zones"]:
        assert rows[zone["slug"]].zone_id is None and rows[zone["slug"]].name == zone["name"]
    for place in campus["locations"]:
        row = rows[place["slug"]]
        assert not row.is_zone and row.is_active and row.name == place["name"]
        assert row.location_id == seed_id("location", place["slug"]) and row.zone_id == seed_id("location", place["zone_slug"])
    before = reference_counts(db)

    assert run_cli(["seed-reference-data", "--config", str(EXAMPLE_CONFIG)]) == cli.EXIT_OK
    second = capsys.readouterr().out
    assert "categories=0, zones=0, locations=0" in second and "already up to date" in second and "WARNING" not in second
    assert reference_counts(db) == before and count(db, User) == 0  # no duplicates, and seeding never creates accounts


def test_seed_uses_the_configured_default_path_when_no_config_is_given(blank_reference_data, db, monkeypatch):
    monkeypatch.setattr(cli, "get_settings", lambda: SimpleNamespace(campus_config_file=lambda: EXAMPLE_CONFIG))
    assert run_cli(["seed-reference-data"]) == cli.EXIT_OK
    assert count(db, Category) == len(json.loads(EXAMPLE_CONFIG.read_text(encoding="utf-8"))["categories"])


def test_seed_never_renames_existing_rows_but_still_adds_new_ones(blank_reference_data, db, tmp_path, capsys):
    campus = copy.deepcopy(get_campus_config())
    assert run_cli(["seed-reference-data", "--config", write_config(tmp_path, campus)]) == cli.EXIT_OK
    capsys.readouterr()
    campus["categories"][0]["name"] = "Renamed Electronics"
    campus["categories"].append({"slug": "keys", "name": "Keys"})
    assert run_cli(["seed-reference-data", "--config", write_config(tmp_path, campus)]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "categories=1" in out and "WARNING" in out and f"category:{campus['categories'][0]['slug']}" in out
    db.expire_all()
    assert db.get(Category, seed_id("category", campus["categories"][0]["slug"])).name == "Electronics"
    assert db.get(Category, seed_id("category", "keys")).name == "Keys"


def test_a_failing_seed_rolls_back_everything_it_did(blank_reference_data, db, tmp_path, capsys):
    campus = copy.deepcopy(get_campus_config())
    assert run_cli(["seed-reference-data", "--config", write_config(tmp_path, campus)]) == cli.EXIT_OK
    capsys.readouterr()
    before = reference_counts(db)
    clash = copy.deepcopy(campus)
    clash["categories"].append({"slug": "zz-extra", "name": "Extra"})  # valid and inserted first ...
    clash["locations"] = [loc for loc in clash["locations"] if loc["slug"] != "lab"]
    clash["locations"].append({"slug": "lab-2", "name": "Laboratories", "zone_slug": "academic-zone"})  # ... name taken by `lab`
    assert run_cli(["seed-reference-data", "--config", write_config(tmp_path, clash)]) == cli.EXIT_FAILURE
    err = capsys.readouterr().err
    assert "rolled back" in err and "IntegrityError" in err and "INSERT" not in err and "Laboratories" not in err
    assert reference_counts(db) == before and db.get(Category, seed_id("category", "zz-extra")) is None


def _zone_slug_reused_by_a_location(c):
    c["locations"].append({"slug": c["zones"][0]["slug"], "name": "Clashing Place", "zone_slug": c["zones"][1]["slug"]})


@pytest.mark.parametrize("mutate", [
    lambda c: c.pop("timezone"),
    lambda c: c.update(timezone="Mars/Olympus_Mons"),
    lambda c: c["categories"].append(dict(c["categories"][0])),
    lambda c: c["locations"].append({"slug": "ghost", "name": "Ghost Wing", "zone_slug": "no-such-zone"}),
    _zone_slug_reused_by_a_location,
])
def test_an_invalid_config_is_refused_without_touching_the_database(db, tmp_path, capsys, mutate):
    campus = copy.deepcopy(get_campus_config())
    mutate(campus)
    before = reference_counts(db)
    assert run_cli(["seed-reference-data", "--config", write_config(tmp_path, campus)]) == cli.EXIT_USAGE
    assert capsys.readouterr().err.strip() and reference_counts(db) == before


@pytest.mark.parametrize("content", ["{not json", "[]", ""])
def test_unreadable_or_malformed_config_files_are_refused(db, tmp_path, capsys, content):
    before = reference_counts(db)
    assert run_cli(["seed-reference-data", "--config", write_config(tmp_path, content)]) == cli.EXIT_USAGE
    assert reference_counts(db) == before


def test_a_missing_config_file_is_refused_with_guidance(db, tmp_path, capsys):
    assert run_cli(["seed-reference-data", "--config", str(tmp_path / "nope.json")]) == cli.EXIT_USAGE
    assert "not found" in capsys.readouterr().err


# ------------------------------------------------------------------------------------ cleanup-retention

def summary_line(out: str, label: str) -> dict[str, int]:
    line = next(ln for ln in out.splitlines() if ln.strip().startswith(label))
    return {k: int(v) for k, v in re.findall(r"(\w+)=(\d+)", line)}


def test_cleanup_command_really_deletes_expired_photos_and_evidence(db, cli_store, capsys):
    due_photo = photo(db, cli_store, terminal_report(db, "CLOSED", 91))
    due_evidence = evidence(db, cli_store, terminal_claim(db, "RECOVERED", 91))
    young_photo = photo(db, cli_store, terminal_report(db, "CLOSED", 10))
    live_evidence = evidence(db, cli_store, terminal_claim(db, "PENDING", 500), purge_days=None)
    secrets = (due_photo.blob_key, due_evidence.blob_key, young_photo.blob_key, SECRET_FILENAME, "attachments/")
    kept = (young_photo.blob_key, live_evidence.blob_key)
    db.commit()

    assert run_cli(["cleanup-retention"]) == cli.EXIT_OK
    out = capsys.readouterr()
    assert summary_line(out.out, "Report photos") == {"eligible": 1, "purged": 1, "deferred": 0, "failed": 0}
    assert summary_line(out.out, "Claim evidence") == {"eligible": 1, "purged": 1, "deferred": 0, "failed": 0}
    assert "Audit event: recorded" in out.out

    assert not has_blob(cli_store, due_photo.blob_key) and not has_blob(cli_store, due_evidence.blob_key)
    assert all(has_blob(cli_store, key) for key in kept)
    assert att_state(db, due_photo)[0] == "DELETED" and ev_state(db, due_evidence)[0] == "DELETED"
    assert att_state(db, young_photo)[0] == "ACTIVE" and ev_state(db, live_evidence)[0] == "ACTIVE"
    assert not any(s in out.out + out.err for s in secrets)  # counts only: no keys, filenames or paths


def test_repeating_the_cleanup_command_is_safe_and_finds_nothing(db, cli_store, capsys):
    att = photo(db, cli_store, terminal_report(db))
    db.commit()
    assert run_cli(["cleanup-retention"]) == cli.EXIT_OK
    capsys.readouterr()
    deleted_at = att_state(db, att)[1]
    assert run_cli(["cleanup-retention"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert summary_line(out, "Report photos")["eligible"] == 0 and att_state(db, att)[1] == deleted_at


def test_cleanup_dry_run_counts_but_changes_nothing(db, cli_store, capsys):
    att = photo(db, cli_store, terminal_report(db))
    ev = evidence(db, cli_store, terminal_claim(db))
    db.commit()
    assert run_cli(["cleanup-retention", "--dry-run"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "DRY RUN" in out and summary_line(out, "Report photos")["eligible"] == 1
    assert summary_line(out, "Report photos")["purged"] == 0 and "Audit event" not in out
    assert has_blob(cli_store, att.blob_key) and has_blob(cli_store, ev.blob_key)
    assert att_state(db, att)[0] == "ACTIVE" and ev_state(db, ev)[0] == "ACTIVE"
    assert count(db, ActivityLog) == 0


def test_cleanup_storage_failure_exits_nonzero_keeps_data_and_the_next_run_recovers(db, flaky_store, capsys):
    att = photo(db, flaky_store, terminal_report(db))
    db.commit()
    flaky_store.fail_delete = True
    assert run_cli(["cleanup-retention"]) == cli.EXIT_FAILURE
    out = capsys.readouterr()
    assert summary_line(out.out, "Report photos")["failed"] == 1 and "failure(s)" in out.err
    assert has_blob(flaky_store, att.blob_key) and att_state(db, att) == ("ACTIVE", None)

    flaky_store.fail_delete = False
    assert run_cli(["cleanup-retention"]) == cli.EXIT_OK
    assert not has_blob(flaky_store, att.blob_key) and att_state(db, att)[0] == "DELETED"


def test_cleanup_without_configured_storage_fails_clearly_and_deletes_nothing(db, capsys):
    set_blob_store(None)  # conftest blanks LOCAL_BLOB_DIR and the Azure account URL: no store can resolve
    assert run_cli(["cleanup-retention"]) == cli.EXIT_FAILURE
    assert "STORAGE_NOT_CONFIGURED" in capsys.readouterr().out


def test_cleanup_reports_a_database_failure_without_leaking_sql_or_parameters(monkeypatch, capsys):
    def boom(**_kw):
        raise OperationalError("SELECT * FROM secret_table WHERE k = ?", {"k": "s3cret-param"}, Exception("login failed for user sa"))

    monkeypatch.setattr(cli.cleanup, "run_retention_cleanup", boom)
    assert run_cli(["cleanup-retention"]) == cli.EXIT_FAILURE
    out = capsys.readouterr()
    assert "OperationalError" in out.err
    assert not any(s in out.out + out.err for s in ("secret_table", "s3cret-param", "login failed"))


# ------------------------------------------------------------------------------------ matching-jobs

def queued_pair(db):
    """A LOST and a FOUND report that match each other, each with its outbox job. Returns (lost_id, found_id, jobs)."""
    lost = make_report(db, make_user(db), "LOST")
    found = make_report(db, make_user(db), "FOUND")
    jobs = [enqueue_job(db, lost, "t-lost").job_id, enqueue_job(db, found, "t-found").job_id]
    ids = (lost.report_id, found.report_id, jobs)
    db.commit()
    return ids


def job_of(db, job_id) -> MatchingJob:
    db.expire_all()
    row = db.get(MatchingJob, job_id)
    assert row is not None
    return row


def dead_job(db, title: str = "Dead job item") -> tuple[uuid.UUID, uuid.UUID]:
    report = make_report(db, make_user(db), "FOUND", title=title)
    job = enqueue_job(db, report, "t-dead")
    job.status, job.attempt_count, job.last_error_code, job.next_attempt_at_utc = "DEAD", matching_worker.MAX_ATTEMPTS, "ERR_Boom", None
    ids = (report.report_id, job.job_id)
    db.commit()
    return ids


def test_matching_jobs_run_processes_due_jobs_through_the_existing_worker(db, capsys):
    _, _, jobs = queued_pair(db)
    assert run_cli(["matching-jobs", "run"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "processed=2 succeeded=2" in out and "due=2" in out.split("Queue after")[0] and "due=0" in out.split("Queue after")[1]
    assert all(job_of(db, j).status == "SUCCEEDED" for j in jobs)
    match = db.scalars(select(Match)).one()
    assert match.algorithm_version == "match-v1"

    assert run_cli(["matching-jobs", "run"]) == cli.EXIT_OK  # nothing left: a second run is a no-op
    assert "processed=0" in capsys.readouterr().out and count(db, Match) == 1


def test_max_jobs_stops_the_run_and_the_next_run_finishes_the_rest(db, capsys):
    _, _, jobs = queued_pair(db)
    assert run_cli(["matching-jobs", "run", "--max-jobs", "1"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "processed=1" in out and "Stopped at --max-jobs=1" in out
    assert sorted(job_of(db, j).status for j in jobs) == ["PENDING", "SUCCEEDED"]
    assert run_cli(["matching-jobs", "run", "--max-jobs", "5"]) == cli.EXIT_OK
    assert "processed=1" in capsys.readouterr().out and all(job_of(db, j).status == "SUCCEEDED" for j in jobs)


def test_run_reclaims_stale_leases_and_leaves_active_leases_backoff_and_dead_jobs_alone(db, capsys):
    now = utcnow()
    jobs = {}
    for name in ("stale", "active", "backoff", "dead"):
        jobs[name] = enqueue_job(db, make_report(db, make_user(db), "FOUND", title=f"{name} item"), f"t-{name}")
    jobs["stale"].status, jobs["stale"].lease_expires_at_utc = "PROCESSING", now - dt.timedelta(minutes=5)
    jobs["active"].status, jobs["active"].lease_expires_at_utc = "PROCESSING", now + dt.timedelta(minutes=5)
    jobs["backoff"].next_attempt_at_utc = now + dt.timedelta(hours=1)
    jobs["dead"].status, jobs["dead"].next_attempt_at_utc = "DEAD", None
    ids = {k: v.job_id for k, v in jobs.items()}
    db.commit()

    assert run_cli(["matching-jobs", "run"]) == cli.EXIT_OK  # an existing DEAD job alone does not fail the run
    out = capsys.readouterr().out
    assert "processed=1" in out and "stale_reclaimable=1" in out and "backoff=1" in out and "leased=1" in out
    assert "1 DEAD job(s) need attention" in out
    assert {k: job_of(db, v).status for k, v in ids.items()} == {
        "stale": "SUCCEEDED", "active": "PROCESSING", "backoff": "PENDING", "dead": "DEAD"}


def test_a_failing_job_is_retried_with_backoff_and_not_picked_up_again_at_once(db, capsys, monkeypatch):
    _, _, jobs = queued_pair(db)
    with get_sessionmaker()() as s:  # two earlier failures: this one is attempt 3, so the delay is 8 s, far beyond this run
        for j in jobs:
            s.get(MatchingJob, j).attempt_count = 2
        s.commit()

    def boom(*_a, **_k):
        raise RuntimeError("scoring exploded with private text")

    monkeypatch.setattr(matching_worker.m, "score_pair", boom)
    assert run_cli(["matching-jobs", "run"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "processed=2" in out and "failed_retry_scheduled=2" in out and "failed_dead=0" in out
    for j in jobs:
        row = job_of(db, j)
        assert (row.status, row.attempt_count, row.last_error_code) == ("PENDING", 3, "ERR_RuntimeError")
        assert row.next_attempt_at_utc is not None and row.next_attempt_at_utc > utcnow() + dt.timedelta(seconds=3)
        assert row.lease_expires_at_utc is None
    assert run_cli(["matching-jobs", "run"]) == cli.EXIT_OK and "processed=0" in capsys.readouterr().out


def test_a_job_that_reaches_the_attempt_limit_goes_dead_and_the_run_exits_nonzero(db, capsys, monkeypatch):
    lost_id, found_id, jobs = queued_pair(db)
    with get_sessionmaker()() as s:
        for j in jobs:
            s.get(MatchingJob, j).attempt_count = matching_worker.MAX_ATTEMPTS - 1
        s.commit()

    def boom(*_a, **_k):
        raise RuntimeError("scoring exploded with private text")

    monkeypatch.setattr(matching_worker.m, "score_pair", boom)
    assert run_cli(["matching-jobs", "run"]) == cli.EXIT_FAILURE
    out = capsys.readouterr().out
    assert "failed_dead=2" in out and "2 DEAD job(s) need attention" in out and "private text" not in out
    for j in jobs:
        row = job_of(db, j)
        assert (row.status, row.attempt_count, row.next_attempt_at_utc) == ("DEAD", matching_worker.MAX_ATTEMPTS, None)
    db.expire_all()
    assert db.get(Report, lost_id).status == "ACTIVE" and db.get(Report, found_id).status == "ACTIVE"  # report writes are never rolled back
    events = db.scalars(select(ActivityLog).where(ActivityLog.event_type == "MATCH_JOB_FAILED")).all()
    assert len(events) == 2 and all("private text" not in (e.metadata_json or "") for e in events)


def test_list_shows_dead_jobs_with_ids_only(db, capsys):
    report_id, job_id = dead_job(db, title="Very Private Title")
    assert run_cli(["matching-jobs", "list"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "1 DEAD matching job(s)" in out and str(job_id) in out and str(report_id) in out and "ERR_Boom" in out
    assert "matching-jobs retry" in out and "Very Private Title" not in out


def test_list_filters_by_status_and_limits_rows(db, capsys):
    dead_job(db, "one")
    dead_job(db, "two")
    queued_pair(db)
    assert run_cli(["matching-jobs", "list", "--limit", "1"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "2 DEAD matching job(s) (showing 1)" in out and out.count("report=") == 1
    assert run_cli(["matching-jobs", "list", "--status", "PENDING"]) == cli.EXIT_OK
    assert "2 PENDING matching job(s)" in capsys.readouterr().out
    assert run_cli(["matching-jobs", "list", "--status", "SUCCEEDED"]) == cli.EXIT_OK
    assert "0 SUCCEEDED matching job(s)" in capsys.readouterr().out


def test_retry_requeues_one_dead_job_audits_the_operator_and_the_worker_then_completes_it(db, capsys):
    report_id, job_id = dead_job(db)
    other_report, other_job = dead_job(db, "untouched")
    report_before = db.get(Report, report_id)
    report_state = (report_before.status, report_before.version, report_before.matching_version)
    db.commit()

    assert run_cli(["matching-jobs", "retry", str(job_id)]) == cli.EXIT_OK
    assert "requeued as PENDING" in capsys.readouterr().out
    row = job_of(db, job_id)
    assert (row.status, row.attempt_count, row.last_error_code, row.lease_expires_at_utc) == ("PENDING", 0, None, None)
    assert row.next_attempt_at_utc is not None and row.next_attempt_at_utc <= utcnow()
    assert job_of(db, other_job).status == "DEAD"  # only the named job moves
    event = db.scalars(select(ActivityLog).where(ActivityLog.event_type == "MATCH_JOB_RETRIED")).one()
    assert event.actor_user_id is None and event.outcome == "SUCCESS" and event.target_id == report_id
    meta = json.loads(event.metadata_json)
    assert meta["operator"] == "OPERATOR" and meta["job_id"] == str(job_id) and meta["attempt_count"] == matching_worker.MAX_ATTEMPTS
    assert meta["error_code"] == "ERR_Boom"
    after = db.get(Report, report_id)
    assert (after.status, after.version, after.matching_version) == report_state  # report workflow is untouched

    assert run_cli(["matching-jobs", "run"]) == cli.EXIT_OK  # the existing worker picks the requeued job up
    assert "processed=1 succeeded=1" in capsys.readouterr().out and job_of(db, job_id).status == "SUCCEEDED"


def test_retry_refuses_jobs_that_are_not_dead_and_unknown_jobs(db, capsys):
    _, _, jobs = queued_pair(db)
    pending = jobs[0]
    assert run_cli(["matching-jobs", "retry", str(pending)]) == cli.EXIT_FAILURE
    assert "JOB_NOT_DEAD" in capsys.readouterr().err and job_of(db, pending).status == "PENDING"
    assert run_cli(["matching-jobs", "retry", str(uuid.uuid4())]) == cli.EXIT_FAILURE
    assert "JOB_NOT_FOUND" in capsys.readouterr().err
    assert db.scalar(select(func.count()).select_from(ActivityLog).where(ActivityLog.event_type == "MATCH_JOB_RETRIED")) == 0


def test_retrying_the_same_job_twice_is_refused_the_second_time(db, capsys):
    _, job_id = dead_job(db)
    assert run_cli(["matching-jobs", "retry", str(job_id)]) == cli.EXIT_OK
    capsys.readouterr()
    assert run_cli(["matching-jobs", "retry", str(job_id)]) == cli.EXIT_FAILURE
    assert "JOB_NOT_DEAD" in capsys.readouterr().err
    assert db.scalar(select(func.count()).select_from(ActivityLog).where(ActivityLog.event_type == "MATCH_JOB_RETRIED")) == 1


@pytest.mark.parametrize(("argv", "marker"), [
    (["matching-jobs", "run"], "DATABASE_URL"), (["matching-jobs", "list"], "DATABASE_URL"),
    (["cleanup-retention"], "DATABASE_URL"), (["seed-reference-data"], "rolled back"),
])
def test_a_database_outage_is_reported_without_sql_text_or_parameters(monkeypatch, capsys, argv, marker):
    def boom(*_a, **_k):
        raise OperationalError("SELECT secret FROM t WHERE p = ?", {"p": "hunter2-parameter"}, Exception("Login failed for user 'sa'"))

    monkeypatch.setattr(cli.operator, "run_matching_jobs", boom)
    monkeypatch.setattr(cli.operator, "list_jobs", boom)
    monkeypatch.setattr(cli.cleanup, "run_retention_cleanup", boom)
    monkeypatch.setattr(cli, "load_campus_config", lambda _p: {"x": 1})
    monkeypatch.setattr(cli.operator, "seed_campus", boom)
    assert run_cli(argv) == cli.EXIT_FAILURE
    err = capsys.readouterr().err
    assert "OperationalError" in err and marker in err
    assert not any(s in err for s in ("SELECT", "hunter2-parameter", "Login failed"))


def test_a_missing_database_configuration_is_reported_plainly(monkeypatch, capsys):
    def unconfigured(*_a, **_k):
        raise RuntimeError("DATABASE_URL is not configured")

    monkeypatch.setattr(cli.operator, "run_matching_jobs", unconfigured)
    assert run_cli(["matching-jobs", "run"]) == cli.EXIT_FAILURE
    assert "DATABASE_URL is not configured" in capsys.readouterr().err
