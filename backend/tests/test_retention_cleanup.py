"""Retention executor (contract A10, A24). Real SQL Server, controlled LocalBlobStore, injected clock.

Clock control: `run_retention_cleanup(now=...)` is injected, so "91 days later" never needs sleeping or fake time.
Test data is always committed before the executor runs because the executor uses its own sessions, like production.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import threading
import uuid

import pytest
from sqlalchemy import func, select

from app.core.security import new_id, utcnow
from app.persistence.database import get_sessionmaker
from app.persistence.models import (
    ActivityLog,
    Attachment,
    Claim,
    ClaimEvidence,
    ClaimStatusHistory,
    Report,
    ReportStatusHistory,
)
from app.services import audit, cleanup, retention
from app.services.blobstore import BlobUnavailableError, LocalBlobStore, set_blob_store
from tests import image_fixtures as fx
from tests.api_helpers import login_api, report_body
from tests.helpers import make_claim, make_report, make_user

pytestmark = pytest.mark.sql

DAY = dt.timedelta(days=1)
SECRET_FILENAME = "very-private-name.jpg"


@pytest.fixture()
def store(tmp_path):
    s = LocalBlobStore(str(tmp_path / "blobs"))
    set_blob_store(s)
    yield s
    set_blob_store(None)


class FlakyStore(LocalBlobStore):
    """Real directory store whose delete()/list() fail on demand with the adapter's storage-outage error."""

    fail_delete = False
    fail_list = False
    delete_calls = 0

    def delete(self, key):
        self.delete_calls += 1
        if self.fail_delete:
            raise BlobUnavailableError
        super().delete(key)

    def list(self, prefix="attachments/"):
        if self.fail_list:
            raise BlobUnavailableError
        return super().list(prefix)


class LockedFileStore(LocalBlobStore):
    """delete() raises a plain OSError, as a locked file on Windows would."""

    def delete(self, key):
        raise PermissionError("file is in use")


@pytest.fixture()
def flaky(tmp_path):
    s = FlakyStore(str(tmp_path / "flaky"))
    set_blob_store(s)
    yield s
    set_blob_store(None)


# ------------------------------------------------------------------------------------ builders

def new_key(ext: str = "jpg") -> str:
    return f"attachments/{uuid.uuid4()}.{ext}"


def put_blob(store: LocalBlobStore, key: str | None = None, age: dt.timedelta = 2 * DAY) -> str:
    key = key or new_key()
    store.put(key, b"private-evidence-bytes", "image/jpeg")
    stamp = (utcnow() - age).timestamp()
    os.utime(store.root / key, (stamp, stamp))
    return key


def terminal_report(db, status: str = "CLOSED", terminal_days: float = 91) -> Report:
    report = make_report(db, make_user(db), "FOUND", status=status)
    report.status_changed_at_utc = utcnow() - dt.timedelta(days=terminal_days)
    db.flush()
    return report


def photo(db, store, report: Report, *, purge_days: float | None = 90, status: str = "ACTIVE", blob: bool = True) -> Attachment:
    """`purge_days` = days after the report's terminal transition (None = never scheduled)."""
    att = Attachment(
        attachment_id=new_id(), report_id=report.report_id, uploaded_by_user_id=report.reporter_user_id,
        attachment_type="REPORT_PHOTO", blob_key=put_blob(store) if blob else new_key(), original_filename=SECRET_FILENAME,
        content_type="image/jpeg", size_bytes=22, upload_status=status, created_at_utc=utcnow(),
        purge_after_utc=None if purge_days is None else report.status_changed_at_utc + dt.timedelta(days=purge_days),
    )
    db.add(att)
    db.flush()
    return att


def terminal_claim(db, status: str = "RECOVERED", terminal_days: float = 91) -> Claim:
    found = make_report(db, make_user(db), "FOUND")
    claim = make_claim(db, make_user(db), found, status=status)
    claim.status_changed_at_utc = utcnow() - dt.timedelta(days=terminal_days)
    db.flush()
    return claim


def evidence(db, store, claim: Claim, *, purge_days: float | None = 90, status: str = "ACTIVE", blob: bool = True) -> ClaimEvidence:
    ev = ClaimEvidence(
        evidence_id=new_id(), claim_id=claim.claim_id, uploaded_by_user_id=claim.claimant_user_id,
        blob_key=put_blob(store) if blob else new_key(), original_filename=SECRET_FILENAME, content_type="image/jpeg",
        size_bytes=22, upload_status=status, uploaded_at_utc=utcnow(),
        purge_after_utc=None if purge_days is None else claim.status_changed_at_utc + dt.timedelta(days=purge_days),
    )
    db.add(ev)
    db.flush()
    return ev


def att_state(db, att: Attachment) -> tuple[str, dt.datetime | None]:
    db.expire_all()
    row = db.get(Attachment, att.attachment_id)
    assert row is not None, "attachment metadata must never be hard-deleted"
    return row.upload_status, row.deleted_at_utc


def ev_state(db, ev: ClaimEvidence) -> tuple[str, dt.datetime | None]:
    db.expire_all()
    row = db.get(ClaimEvidence, ev.evidence_id)
    assert row is not None, "evidence metadata must never be hard-deleted"
    return row.upload_status, row.deleted_at_utc


def has_blob(store: LocalBlobStore, key: str) -> bool:
    return (store.root / key).exists()


def cleanup_events(db) -> list[ActivityLog]:
    db.expire_all()
    return list(db.scalars(select(ActivityLog).where(ActivityLog.event_type == "RETENTION_CLEANUP").order_by(ActivityLog.created_at_utc)))


def run(store, now: dt.datetime | None = None, **kw) -> cleanup.CleanupSummary:
    return cleanup.run_retention_cleanup(store=store, now=now or utcnow(), **kw)


# ------------------------------------------------------------------------------------ report photos

@pytest.mark.parametrize("status", ["RESOLVED", "WITHDRAWN", "CLOSED"])
def test_report_photo_is_purged_for_every_terminal_state(db, store, status):
    att = photo(db, store, terminal_report(db, status))
    key = att.blob_key
    db.commit()
    s = run(store)
    assert (s.attachments_eligible, s.attachments_purged, s.attachments_failed) == (1, 1, 0)
    assert not has_blob(store, key)
    state, deleted_at = att_state(db, att)
    assert state == "DELETED" and deleted_at is not None


def test_report_photo_not_yet_due_is_kept(db, store):
    att = photo(db, store, terminal_report(db, "CLOSED", terminal_days=89))
    db.commit()
    s = run(store)
    assert (s.attachments_eligible, s.attachments_purged) == (0, 0)
    assert has_blob(store, att.blob_key) and att_state(db, att)[0] == "ACTIVE"


def test_age_is_measured_from_the_terminal_timestamp_to_the_day(db, store):
    due = photo(db, store, terminal_report(db, "CLOSED", terminal_days=90.01), purge_days=90)
    not_due = photo(db, store, terminal_report(db, "CLOSED", terminal_days=89.99), purge_days=90)
    db.commit()
    s = run(store)
    assert s.attachments_purged == 1
    assert att_state(db, due)[0] == "DELETED" and att_state(db, not_due)[0] == "ACTIVE"


@pytest.mark.parametrize("status", ["ACTIVE"])
def test_nonterminal_report_is_never_purged_even_with_a_stale_schedule(db, store, status):
    report = terminal_report(db, status, terminal_days=400)  # ACTIVE for ages, but a leftover schedule is long past
    att = photo(db, store, report, purge_days=90)
    db.commit()
    s = run(store)
    assert s.attachments_eligible == 0 and s.attachments_purged == 0
    assert has_blob(store, att.blob_key) and att_state(db, att)[0] == "ACTIVE"


def test_photo_on_resolved_report_that_was_never_scheduled_is_still_purged_on_time(db, store):
    """A photo can be uploaded to an already RESOLVED report; nothing schedules it, so age comes from the terminal time."""
    old = photo(db, store, terminal_report(db, "RESOLVED", terminal_days=120), purge_days=None)
    young = photo(db, store, terminal_report(db, "RESOLVED", terminal_days=40), purge_days=None)
    db.commit()
    s = run(store)
    assert s.attachments_purged == 1
    assert att_state(db, old)[0] == "DELETED" and att_state(db, young)[0] == "ACTIVE"


def test_a_too_early_schedule_can_never_shorten_the_90_day_period(db, store):
    att = photo(db, store, terminal_report(db, "CLOSED", terminal_days=30), purge_days=-60)  # purge_after in the past
    db.commit()
    s = run(store)
    assert s.attachments_purged == 0 and has_blob(store, att.blob_key)


def test_a_later_schedule_is_respected(db, store):
    att = photo(db, store, terminal_report(db, "CLOSED", terminal_days=200), purge_days=205)  # due in 5 days
    db.commit()
    assert run(store).attachments_purged == 0 and has_blob(store, att.blob_key)
    assert run(store, now=utcnow() + 6 * DAY).attachments_purged == 1


def test_scheduler_and_executor_agree(db, store):
    """The scheduler (retention.py) sets purge_after_utc; reopening cancels it; the executor honours both."""
    report = make_report(db, make_user(db), "FOUND")
    att = photo(db, store, report, purge_days=None)
    terminal_at = (utcnow() - 91 * DAY).replace(microsecond=0)  # SQL Server datetime2(3) keeps milliseconds only
    report.status, report.status_changed_at_utc = "CLOSED", terminal_at
    retention.schedule_purge_for_report(db, report.report_id, terminal_at)
    db.commit()
    db.expire_all()
    assert db.get(Attachment, att.attachment_id).purge_after_utc == terminal_at + dt.timedelta(days=90)

    report = db.get(Report, report.report_id)  # moderator reopens before the purge runs
    report.status = "ACTIVE"
    retention.cancel_purge_for_report(db, report.report_id)
    db.commit()
    assert run(store).attachments_purged == 0 and has_blob(store, att.blob_key)

    report = db.get(Report, report.report_id)  # withdrawn again: the NEW terminal transition restarts the clock
    report.status, report.status_changed_at_utc = "WITHDRAWN", utcnow() - 10 * DAY
    retention.schedule_purge_for_report(db, report.report_id, report.status_changed_at_utc)
    db.commit()
    assert run(store).attachments_purged == 0 and has_blob(store, att.blob_key)
    assert run(store, now=utcnow() + 81 * DAY).attachments_purged == 1


def test_pending_cleanup_rows_are_removed_regardless_of_report_state(db, store):
    att = photo(db, store, make_report(db, make_user(db), "FOUND"), status="PENDING_CLEANUP", purge_days=None)
    db.commit()
    s = run(store)
    assert s.attachments_purged == 1 and not has_blob(store, att.blob_key)
    assert att_state(db, att)[0] == "DELETED"


def test_already_deleted_rows_are_ignored_and_never_hard_deleted(db, store):
    att = photo(db, store, terminal_report(db), status="DELETED", blob=False)
    att.deleted_at_utc = utcnow() - 5 * DAY
    db.commit()
    before = db.scalar(select(func.count()).select_from(Attachment))
    s = run(store)
    assert s.attachments_eligible == 0 and db.scalar(select(func.count()).select_from(Attachment)) == before


# ------------------------------------------------------------------------------------ claim evidence

@pytest.mark.parametrize("status", ["RECOVERED", "REJECTED", "CANCELLED"])
def test_claim_evidence_is_purged_for_every_terminal_state(db, store, status):
    ev = evidence(db, store, terminal_claim(db, status))
    key = ev.blob_key
    db.commit()
    s = run(store)
    assert (s.evidence_eligible, s.evidence_purged, s.evidence_failed) == (1, 1, 0)
    assert not has_blob(store, key)
    state, deleted_at = ev_state(db, ev)
    assert state == "DELETED" and deleted_at is not None


@pytest.mark.parametrize("status", ["PENDING", "VERIFIED"])
def test_live_claim_evidence_is_never_purged_even_when_old(db, store, status):
    ev = evidence(db, store, terminal_claim(db, status, terminal_days=500), purge_days=90)
    db.commit()
    s = run(store)
    assert s.evidence_eligible == 0 and has_blob(store, ev.blob_key) and ev_state(db, ev)[0] == "ACTIVE"


def test_claim_evidence_not_yet_due_is_kept(db, store):
    ev = evidence(db, store, terminal_claim(db, "RECOVERED", terminal_days=89))
    db.commit()
    assert run(store).evidence_purged == 0 and has_blob(store, ev.blob_key)


def test_voided_recovery_evidence_is_kept(db, store):
    """Voiding a recovery returns the claim to VERIFIED and cancels the schedule (contract A10)."""
    claim = terminal_claim(db, "RECOVERED", terminal_days=200)
    ev = evidence(db, store, claim, purge_days=90)
    claim.status = "VERIFIED"
    retention.cancel_purge_for_claim(db, claim.claim_id)
    db.commit()
    assert run(store).evidence_purged == 0 and has_blob(store, ev.blob_key) and ev_state(db, ev)[0] == "ACTIVE"


def test_all_evidence_of_a_claim_is_purged_together(db, store):
    claim = terminal_claim(db, "REJECTED")
    items = [evidence(db, store, claim) for _ in range(3)]
    db.commit()
    s = run(store)
    assert s.evidence_purged == 3 and all(ev_state(db, e)[0] == "DELETED" for e in items)
    assert list(store.list()) == []


# ------------------------------------------------------------------------------------ missing blobs, outages, retry

def test_a_missing_blob_counts_as_success_and_metadata_is_marked_deleted(db, store):
    """Also the recovery path for 'Blob deleted, then the process died before the SQL commit'."""
    att = photo(db, store, terminal_report(db), blob=False)
    ev = evidence(db, store, terminal_claim(db), blob=False)
    db.commit()
    s = run(store)
    assert (s.attachments_purged, s.evidence_purged, s.failures) == (1, 1, 0)
    assert att_state(db, att)[0] == "DELETED" and ev_state(db, ev)[0] == "DELETED"


def test_storage_failure_keeps_metadata_and_the_next_run_retries(db, flaky):
    att = photo(db, flaky, terminal_report(db))
    ev = evidence(db, flaky, terminal_claim(db))
    db.commit()
    flaky.fail_delete = True
    s = run(flaky)
    assert (s.attachments_purged, s.evidence_purged) == (0, 0)
    assert (s.attachments_failed, s.evidence_failed) == (1, 1) and not s.ok
    assert has_blob(flaky, att.blob_key) and has_blob(flaky, ev.blob_key)
    assert att_state(db, att) == ("ACTIVE", None) and ev_state(db, ev) == ("ACTIVE", None)
    assert cleanup_events(db)[-1].outcome == "FAILURE"

    flaky.fail_delete = False  # storage recovers
    s2 = run(flaky)
    assert (s2.attachments_purged, s2.evidence_purged, s2.failures) == (1, 1, 0)
    assert att_state(db, att)[0] == "DELETED" and ev_state(db, ev)[0] == "DELETED"
    assert not has_blob(flaky, att.blob_key) and not has_blob(flaky, ev.blob_key)
    assert cleanup_events(db)[-1].outcome == "SUCCESS"


def test_a_plain_oserror_from_storage_is_a_contained_failure(db, tmp_path):
    store = LockedFileStore(str(tmp_path / "locked"))
    att = photo(db, store, terminal_report(db))
    db.commit()
    s = run(store)
    assert s.attachments_failed == 1 and s.attachments_purged == 0 and att_state(db, att)[0] == "ACTIVE"


def test_one_bad_row_does_not_stop_the_run(db, store):
    bad = photo(db, store, terminal_report(db), blob=False)
    bad.blob_key = "not-a-valid-key"  # a malformed key in SQL: the adapter rejects it with ValueError
    good = photo(db, store, terminal_report(db))
    db.commit()
    s = run(store)
    assert (s.attachments_failed, s.attachments_purged) == (1, 1)
    assert att_state(db, bad)[0] == "ACTIVE" and att_state(db, good)[0] == "DELETED"


def test_storage_outage_stops_the_phase_after_five_consecutive_failures(db, flaky):
    rows = [photo(db, flaky, terminal_report(db)) for _ in range(8)]
    db.commit()
    flaky.fail_delete = True
    s = run(flaky)
    assert flaky.delete_calls == cleanup.STORAGE_BREAKER
    assert (s.attachments_failed, s.attachments_deferred, s.attachments_purged) == (5, 3, 0)
    assert "ATTACHMENT_PURGE_STORAGE_UNAVAILABLE" in s.phase_errors
    assert all(att_state(db, r)[0] == "ACTIVE" for r in rows)


def test_a_successful_delete_resets_the_failure_streak(db, flaky):
    rows = [photo(db, flaky, terminal_report(db)) for _ in range(6)]
    db.commit()
    real_delete = LocalBlobStore.delete
    seen = {"n": 0}

    def sometimes(self, key):
        seen["n"] += 1
        if seen["n"] % 2 == 0:
            raise BlobUnavailableError
        real_delete(self, key)

    flaky.delete = sometimes.__get__(flaky)  # alternate fail / succeed: never 5 in a row
    s = run(flaky)
    assert s.attachments_purged == 3 and s.attachments_failed == 3 and "ATTACHMENT_PURGE_STORAGE_UNAVAILABLE" not in s.phase_errors
    assert sum(att_state(db, r)[0] == "DELETED" for r in rows) == 3


# ------------------------------------------------------------------------------------ idempotency, races, concurrency

def test_rerunning_is_safe_and_finds_nothing_left(db, store):
    att = photo(db, store, terminal_report(db))
    ev = evidence(db, store, terminal_claim(db))
    db.commit()
    first = run(store)
    deleted_at = (att_state(db, att)[1], ev_state(db, ev)[1])
    again = run(store)
    assert (first.attachments_purged, first.evidence_purged) == (1, 1)
    assert (again.attachments_eligible, again.evidence_eligible, again.attachments_purged, again.evidence_purged) == (0, 0, 0, 0)
    assert again.ok and (att_state(db, att)[1], ev_state(db, ev)[1]) == deleted_at  # timestamps are not rewritten


def test_reopen_after_listing_but_before_purging_protects_the_photo(db, store):
    att = photo(db, store, terminal_report(db))
    db.commit()
    now = utcnow()
    with get_sessionmaker()() as s:
        items = cleanup._eligible_attachments(s, now)
    assert items == [(att.attachment_id, att.report_id)]
    report = db.get(Report, att.report_id)  # a moderator reopens the report right now
    report.status = "ACTIVE"
    retention.cancel_purge_for_report(db, report.report_id)
    db.commit()
    assert cleanup._purge_attachment(store, now, *items[0]) == "deferred"
    assert has_blob(store, att.blob_key) and att_state(db, att) == ("ACTIVE", None)


def test_void_recovery_after_listing_but_before_purging_protects_the_evidence(db, store):
    claim = terminal_claim(db, "RECOVERED")
    ev = evidence(db, store, claim)
    db.commit()
    now = utcnow()
    with get_sessionmaker()() as s:
        items = cleanup._eligible_evidence(s, now)
    assert items == [(ev.evidence_id, ev.claim_id)]
    claim.status = "VERIFIED"
    retention.cancel_purge_for_claim(db, claim.claim_id)
    db.commit()
    assert cleanup._purge_evidence(store, now, *items[0]) == "deferred"
    assert has_blob(store, ev.blob_key) and ev_state(db, ev) == ("ACTIVE", None)


def test_two_concurrent_runs_purge_every_item_exactly_once(db, store):
    rows = [photo(db, store, terminal_report(db)) for _ in range(6)]
    db.commit()
    now = utcnow()
    results: list[cleanup.CleanupSummary] = []
    barrier = threading.Barrier(2)

    def worker():
        barrier.wait()
        results.append(cleanup.run_retention_cleanup(store=store, now=now))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)
    assert len(results) == 2 and all(r.failures == 0 for r in results)
    assert sum(r.attachments_purged for r in results) == 6
    assert all(att_state(db, r)[0] == "DELETED" for r in rows) and list(store.list()) == []


# ------------------------------------------------------------------------------------ dry run

def test_dry_run_reports_counts_and_changes_nothing(db, store):
    att = photo(db, store, terminal_report(db))
    ev = evidence(db, store, terminal_claim(db))
    orphan = put_blob(store, age=3 * DAY)
    db.add(ActivityLog(activity_id=new_id(), actor_user_id=None, event_type="AUTH_LOGOUT", target_type="NONE", target_id=None,
                       created_at_utc=utcnow() - 400 * DAY, outcome="SUCCESS", correlation_id="old", metadata_json=None))
    db.commit()
    s = run(store, dry_run=True)
    assert (s.attachments_eligible, s.evidence_eligible, s.orphan_blobs_eligible, s.activity_logs_eligible) == (1, 1, 1, 1)
    assert (s.attachments_purged, s.evidence_purged, s.orphan_blobs_removed, s.activity_logs_purged) == (0, 0, 0, 0)
    assert all(has_blob(store, k) for k in (att.blob_key, ev.blob_key, orphan))
    assert att_state(db, att)[0] == "ACTIVE" and ev_state(db, ev)[0] == "ACTIVE"
    assert cleanup_events(db) == [] and db.scalar(select(func.count()).select_from(ActivityLog)) == 1


# ------------------------------------------------------------------------------------ orphan Blobs

def test_orphan_blobs_older_than_24h_are_removed_and_everything_else_is_kept(db, store):
    referenced = photo(db, store, make_report(db, make_user(db), "FOUND"))  # live photo: has a row
    evidenced = evidence(db, store, terminal_claim(db, "PENDING", terminal_days=1), purge_days=None)
    old_orphan = put_blob(store, age=25 * 60 * 60 * dt.timedelta(seconds=1))
    young_orphan = put_blob(store, age=dt.timedelta(hours=23))  # may be an upload whose SQL row is not committed yet
    foreign = "attachments/readme.txt"
    (store.root / "attachments").mkdir(exist_ok=True)
    (store.root / foreign).write_bytes(b"not ours")
    stamp = (utcnow() - 10 * DAY).timestamp()
    os.utime(store.root / foreign, (stamp, stamp))
    db.commit()

    s = run(store)
    assert s.orphan_blobs_removed == 1 and s.orphan_blobs_failed == 0 and s.foreign_blobs_ignored == 1
    assert not has_blob(store, old_orphan)
    assert has_blob(store, young_orphan) and has_blob(store, foreign)
    assert has_blob(store, referenced.blob_key) and has_blob(store, evidenced.blob_key)


def test_a_blob_whose_row_is_marked_deleted_is_not_treated_as_an_orphan_sweep_target_twice(db, store):
    """A row exists (even DELETED), so the 'no SQL row' rule never applies to it."""
    att = photo(db, store, terminal_report(db), status="DELETED")
    att.deleted_at_utc = utcnow() - DAY
    db.commit()
    s = run(store)
    assert s.orphan_blobs_removed == 0 and has_blob(store, att.blob_key)


def test_orphan_listing_outage_is_reported_and_other_phases_still_run(db, flaky):
    att = photo(db, flaky, terminal_report(db))
    db.commit()
    flaky.fail_list = True
    s = run(flaky)
    assert "ORPHAN_SCAN_STORAGE_UNAVAILABLE" in s.phase_errors and not s.ok
    assert s.attachments_purged == 1 and att_state(db, att)[0] == "DELETED"


# ------------------------------------------------------------------------------------ activity logs

def log_row(db, age_days: float, event: str = "AUTH_LOGOUT") -> ActivityLog:
    row = ActivityLog(activity_id=new_id(), actor_user_id=None, event_type=event, target_type="NONE", target_id=None,
                      created_at_utc=utcnow() - dt.timedelta(days=age_days), outcome="SUCCESS", correlation_id="t", metadata_json=None)
    db.add(row)
    db.flush()
    return row


def test_activity_logs_older_than_365_days_are_purged_and_newer_are_kept(db, store):
    old = [log_row(db, 366), log_row(db, 500)]
    keep = [log_row(db, 364), log_row(db, 1)]
    old_ids, keep_ids = [r.activity_id for r in old], [r.activity_id for r in keep]  # read before rows are deleted/expired
    db.commit()
    s = run(store)
    assert s.activity_logs_purged == 2
    db.expire_all()
    remaining = set(db.scalars(select(ActivityLog.activity_id)))
    assert all(i not in remaining for i in old_ids) and all(i in remaining for i in keep_ids)
    assert len(cleanup_events(db)) == 1  # the run's own audit event survives its own purge


def test_activity_log_purge_runs_in_batches_until_done(db, store, monkeypatch):
    monkeypatch.setattr(cleanup, "LOG_BATCH", 2)
    for _ in range(5):
        log_row(db, 400)
    db.commit()
    s = run(store)
    assert s.activity_logs_purged == 5
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(ActivityLog).where(ActivityLog.event_type == "AUTH_LOGOUT")) == 0


def test_status_history_and_workflow_rows_are_never_purged(db, store):
    report = terminal_report(db, "CLOSED", terminal_days=800)
    claim = terminal_claim(db, "RECOVERED", terminal_days=800)
    db.add(ClaimStatusHistory(history_id=new_id(), claim_id=claim.claim_id, old_status="VERIFIED", new_status="RECOVERED",
                              changed_by_user_id=None, changed_at_utc=utcnow() - 800 * DAY, reason_code="RECOVERY_COMPLETED",
                              note=None, correlation_id="old"))
    db.commit()
    counts = lambda: tuple(db.scalar(select(func.count()).select_from(m)) for m in (Report, Claim, ClaimStatusHistory, ReportStatusHistory))  # noqa: E731
    before = counts()
    run(store)
    db.expire_all()
    assert counts() == before and db.get(Report, report.report_id) is not None


def test_logs_are_purged_even_when_blob_storage_is_not_configured(db):
    set_blob_store(None)  # conftest removes LOCAL_BLOB_DIR and no Azure account is configured
    log_row(db, 400)
    db.commit()
    s = cleanup.run_retention_cleanup(now=utcnow())
    assert "STORAGE_NOT_CONFIGURED" in s.phase_errors and not s.ok
    assert s.activity_logs_purged == 1 and s.attachments_eligible == 0
    assert cleanup_events(db)[-1].outcome == "FAILURE"


# ------------------------------------------------------------------------------------ audit and privacy

def test_audit_event_records_counts_only(db, store):
    att = photo(db, store, terminal_report(db))
    ev = evidence(db, store, terminal_claim(db))
    orphan = put_blob(store, age=3 * DAY)
    log_row(db, 400)
    db.commit()
    run(store)
    events = cleanup_events(db)
    assert len(events) == 1
    e = events[0]
    assert e.outcome == "SUCCESS" and e.actor_user_id is None and e.target_id is None
    meta = json.loads(e.metadata_json)
    assert meta == {"purged_attachments": 1, "purged_evidence": 1, "purged_logs": 1, "orphan_blobs_removed": 1,
                    "failures": 0, "operator": "OPERATOR"}
    assert set(meta) <= audit.ALLOWED_METADATA_KEYS
    raw = e.metadata_json + (e.correlation_id or "")
    for secret in (att.blob_key, ev.blob_key, orphan, SECRET_FILENAME, "attachments/"):
        assert secret not in raw


def test_logs_and_summary_never_expose_keys_filenames_or_content(db, flaky, caplog):
    att = photo(db, flaky, terminal_report(db))
    bad = photo(db, flaky, terminal_report(db), blob=False)
    bad.blob_key = "also-not-a-key"
    db.commit()
    flaky.fail_delete = True
    with caplog.at_level(logging.DEBUG):
        s = run(flaky)
    seen = caplog.text + repr(s)
    for secret in (att.blob_key, bad.blob_key, SECRET_FILENAME, "private-evidence-bytes", "attachments/"):
        assert secret not in seen


# ------------------------------------------------------------------------------------ end to end through the API

def test_a_photo_uploaded_through_the_api_is_deleted_by_cleanup_after_the_retention_period(db, store):
    from app.main import create_app

    owner = login_api(create_app(), db, name="Owner")
    rid = owner.post("/api/reports", report_body()).json()["report_id"]
    up = owner.post(f"/api/reports/{rid}/photo", files={"file": ("a.jpg", fx.jpeg_with_exif(), "image/jpeg")})
    assert up.status_code == 201 and len(list(store.list())) == 1
    version = owner.get(f"/api/reports/{rid}").json()["version"]
    assert owner.post(f"/api/reports/{rid}/withdraw", {"expected_version": version}).status_code == 200

    assert run(store, now=utcnow() + 89 * DAY).attachments_purged == 0
    assert owner.get(f"/api/reports/{rid}/photo").status_code == 200  # still within retention

    s = run(store, now=utcnow() + 91 * DAY)
    assert s.attachments_purged == 1 and s.failures == 0
    assert list(store.list()) == []
    assert owner.get(f"/api/reports/{rid}/photo").status_code == 404
    db.expire_all()
    row = db.scalars(select(Attachment).where(Attachment.report_id == uuid.UUID(rid))).one()
    assert row.upload_status == "DELETED" and row.deleted_at_utc is not None  # metadata retained


# ------------------------------------------------------------------------------------ exact boundary

def test_the_90_day_boundary_is_inclusive_to_the_millisecond_for_photos_and_evidence(db, store):
    """Eligible exactly at terminal + 90 days, not one millisecond earlier (injected clock, SQL keeps milliseconds)."""
    terminal_at = utcnow().replace(microsecond=0) - 30 * DAY
    report = terminal_report(db, "CLOSED")
    report.status_changed_at_utc = terminal_at
    claim = terminal_claim(db, "REJECTED")
    claim.status_changed_at_utc = terminal_at
    att = photo(db, store, report, purge_days=None)
    ev = evidence(db, store, claim, purge_days=None)
    db.commit()
    boundary = terminal_at + 90 * DAY

    early = run(store, now=boundary - dt.timedelta(milliseconds=1))
    assert (early.attachments_eligible, early.evidence_eligible, early.attachments_purged, early.evidence_purged) == (0, 0, 0, 0)
    assert has_blob(store, att.blob_key) and has_blob(store, ev.blob_key)

    exact = run(store, now=boundary)
    assert (exact.attachments_purged, exact.evidence_purged, exact.failures) == (1, 1, 0)
    assert not has_blob(store, att.blob_key) and not has_blob(store, ev.blob_key)
    assert att_state(db, att)[0] == "DELETED" and ev_state(db, ev)[0] == "DELETED"


def test_the_365_day_log_boundary_is_exclusive_of_the_cutoff_itself(db, store):
    now = utcnow().replace(microsecond=0)
    at_cutoff = ActivityLog(activity_id=new_id(), actor_user_id=None, event_type="AUTH_LOGOUT", target_type="NONE", target_id=None,
                            created_at_utc=now - 365 * DAY, outcome="SUCCESS", correlation_id="edge", metadata_json=None)
    just_older = ActivityLog(activity_id=new_id(), actor_user_id=None, event_type="AUTH_LOGOUT", target_type="NONE", target_id=None,
                             created_at_utc=now - 365 * DAY - dt.timedelta(milliseconds=1), outcome="SUCCESS", correlation_id="edge",
                             metadata_json=None)
    db.add_all([at_cutoff, just_older])
    kept_id, gone_id = at_cutoff.activity_id, just_older.activity_id
    db.commit()
    assert run(store, now=now).activity_logs_purged == 1
    db.expire_all()
    remaining = set(db.scalars(select(ActivityLog.activity_id)))
    assert kept_id in remaining and gone_id not in remaining
