"""Retention executor (contract A10, A24; Blueprint A6/A10, decisions D-024).

`app.services.retention` only *schedules* purges (`purge_after_utc`); this module *performs* them.

What one run does, in order:
1. Report photos: terminal report (RESOLVED/WITHDRAWN/CLOSED) + 90 days  -> Blob deleted, metadata marked DELETED.
2. Claim evidence: terminal claim (RECOVERED/REJECTED/CANCELLED) + 90 days -> same.
3. Orphan Blobs: objects under `attachments/` with no SQL row (attachments or claim_evidence) older than 24 hours.
4. `activity_logs` rows older than 365 days (status history and workflow rows are never touched).
5. One `RETENTION_CLEANUP` audit event with counts only (never keys, filenames or content).

Safety rules (each one is covered by tests):
- Blob first, then SQL metadata, one transaction per item. A Blob 404 counts as success (the store adapters hide it).
- A Blob failure keeps the metadata untouched; the next run retries. A SQL failure after a successful Blob delete is
  repaired by the next run (the Blob delete is idempotent).
- Eligibility is re-verified under the report/claim row lock immediately before deleting, so a concurrent reopen or
  void-recovery can never lose data to a stale candidate list. Never purges while the owning entity is nonterminal.
- Eligibility needs BOTH `terminal transition + 90 days <= now` and (if scheduled) `purge_after_utc <= now`, so a photo
  uploaded to an already-RESOLVED report (never scheduled) is still purged on time, and a wrongly early schedule can
  never shorten the frozen retention period.
- Metadata rows are retained forever (`deleted_at_utc` set); they are never hard-deleted.
- Logs contain counts and stable codes only: no Blob keys, SAS URLs, filenames, evidence content or SQLAlchemy
  statements (SQLAlchemy errors embed bound parameters, so only the exception class name is logged).
- After 5 consecutive storage failures a phase stops early (storage is down; hammering it helps nobody).
"""

from __future__ import annotations

import datetime as dt
import functools
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.security import utcnow
from app.persistence.database import get_sessionmaker
from app.persistence.models import ActivityLog, Attachment, Claim, ClaimEvidence, Report
from app.services import audit
from app.services.blobstore import BlobStore, BlobUnavailableError, get_blob_store, validate_key
from app.services.locking import lock_claims, lock_reports
from app.services.retention import RETENTION

log = logging.getLogger("findmything.cleanup")

ACTIVITY_LOG_RETENTION = dt.timedelta(days=365)
ORPHAN_MIN_AGE = dt.timedelta(hours=24)
TERMINAL_REPORT = ("RESOLVED", "WITHDRAWN", "CLOSED")
TERMINAL_CLAIM = ("RECOVERED", "REJECTED", "CANCELLED")
STORAGE_BREAKER = 5  # consecutive storage failures before a phase gives up
LOG_BATCH = 5000
ORPHAN_CHECK_CHUNK = 500  # stays far below SQL Server's 2,100 bind-parameter limit
OPERATOR = "OPERATOR"

# LocalBlobStore can raise OSError (e.g. a locked file on Windows); Azure adapters raise BlobUnavailableError.
_STORAGE_ERRORS = (BlobUnavailableError, OSError)

Outcome = Literal["purged", "deferred", "failed", "storage_down"]
Item = tuple[uuid.UUID, uuid.UUID]  # (attachment_id | evidence_id, owning report_id | claim_id)


@dataclass
class CleanupSummary:
    """Counts only. Safe to print and to store: it never carries keys, names or content."""

    dry_run: bool = False
    attachments_eligible: int = 0
    attachments_purged: int = 0
    attachments_deferred: int = 0
    attachments_failed: int = 0
    evidence_eligible: int = 0
    evidence_purged: int = 0
    evidence_deferred: int = 0
    evidence_failed: int = 0
    orphan_blobs_scanned: int = 0
    orphan_blobs_eligible: int = 0
    orphan_blobs_removed: int = 0
    orphan_blobs_failed: int = 0
    foreign_blobs_ignored: int = 0
    activity_logs_eligible: int = 0
    activity_logs_purged: int = 0
    phase_errors: list[str] = field(default_factory=list)
    audit_recorded: bool = False

    @property
    def failures(self) -> int:
        return self.attachments_failed + self.evidence_failed + self.orphan_blobs_failed + len(self.phase_errors)

    @property
    def ok(self) -> bool:
        return self.failures == 0 and (self.dry_run or self.audit_recorded)


# ------------------------------------------------------------------------------------ eligibility

def _is_due(purge_after: dt.datetime | None, terminal_at: dt.datetime, now: dt.datetime) -> bool:
    """Frozen policy: terminal transition + 90 days, and the scheduled `purge_after_utc` when one exists."""
    if terminal_at > now - RETENTION:
        return False
    return purge_after is None or purge_after <= now


def _still_eligible(upload_status: str, purge_after: dt.datetime | None, owner_terminal: bool,
                    terminal_at: dt.datetime, now: dt.datetime) -> bool:
    if upload_status == "PENDING_CLEANUP":  # explicitly flagged "Blob must go" (compensation failed earlier)
        return True
    return upload_status == "ACTIVE" and owner_terminal and _is_due(purge_after, terminal_at, now)


def _eligible_attachments(db: Session, now: dt.datetime) -> list[Item]:
    cutoff = now - RETENTION
    rows = db.execute(
        select(Attachment.attachment_id, Attachment.report_id)
        .join(Report, Report.report_id == Attachment.report_id)
        .where(
            Attachment.deleted_at_utc.is_(None),
            or_(
                Attachment.upload_status == "PENDING_CLEANUP",
                and_(
                    Attachment.upload_status == "ACTIVE",
                    Report.status.in_(TERMINAL_REPORT),
                    Report.status_changed_at_utc <= cutoff,
                    or_(Attachment.purge_after_utc.is_(None), Attachment.purge_after_utc <= now),
                ),
            ),
        )
        .order_by(Attachment.created_at_utc, Attachment.attachment_id)
    ).all()
    return [(r[0], r[1]) for r in rows]


def _eligible_evidence(db: Session, now: dt.datetime) -> list[Item]:
    cutoff = now - RETENTION
    rows = db.execute(
        select(ClaimEvidence.evidence_id, ClaimEvidence.claim_id)
        .join(Claim, Claim.claim_id == ClaimEvidence.claim_id)
        .where(
            ClaimEvidence.deleted_at_utc.is_(None),
            or_(
                ClaimEvidence.upload_status == "PENDING_CLEANUP",
                and_(
                    ClaimEvidence.upload_status == "ACTIVE",
                    Claim.status.in_(TERMINAL_CLAIM),
                    Claim.status_changed_at_utc <= cutoff,
                    or_(ClaimEvidence.purge_after_utc.is_(None), ClaimEvidence.purge_after_utc <= now),
                ),
            ),
        )
        .order_by(ClaimEvidence.uploaded_at_utc, ClaimEvidence.evidence_id)
    ).all()
    return [(r[0], r[1]) for r in rows]


# ------------------------------------------------------------------------------------ per-item purge

def _purge_attachment(store: BlobStore, now: dt.datetime, attachment_id: uuid.UUID, report_id: uuid.UUID) -> Outcome:
    with get_sessionmaker()() as db:
        try:
            report = lock_reports(db, [report_id]).get(report_id)  # serialises with reopen / withdraw / close
            att = db.execute(
                select(Attachment).where(Attachment.attachment_id == attachment_id).execution_options(populate_existing=True)
            ).scalar_one_or_none()
            if report is None or att is None or att.deleted_at_utc is not None:
                db.rollback()
                return "deferred"
            if not _still_eligible(att.upload_status, att.purge_after_utc, report.status in TERMINAL_REPORT,
                                   report.status_changed_at_utc, now):
                db.rollback()
                return "deferred"  # reopened, rescheduled or already purged since the candidate list was built
            try:
                store.delete(att.blob_key)  # Blob first; 404 is success
            except _STORAGE_ERRORS:
                db.rollback()
                return "storage_down"
            except ValueError:  # malformed key in SQL: never let one bad row stop the run
                db.rollback()
                log.error("retention: attachment has an invalid storage key (code=INVALID_BLOB_KEY)")
                return "failed"
            att.upload_status, att.deleted_at_utc = "DELETED", utcnow()
            db.commit()
            return "purged"
        except SQLAlchemyError as exc:
            db.rollback()
            log.error("retention: database error while purging an attachment (type=%s)", type(exc).__name__)
            return "failed"


def _purge_evidence(store: BlobStore, now: dt.datetime, evidence_id: uuid.UUID, claim_id: uuid.UUID) -> Outcome:
    with get_sessionmaker()() as db:
        try:
            claim = lock_claims(db, [claim_id]).get(claim_id)  # serialises with void-recovery / verify / cancel
            ev = db.execute(
                select(ClaimEvidence).where(ClaimEvidence.evidence_id == evidence_id).execution_options(populate_existing=True)
            ).scalar_one_or_none()
            if claim is None or ev is None or ev.deleted_at_utc is not None:
                db.rollback()
                return "deferred"
            if not _still_eligible(ev.upload_status, ev.purge_after_utc, claim.status in TERMINAL_CLAIM,
                                   claim.status_changed_at_utc, now):
                db.rollback()
                return "deferred"
            try:
                store.delete(ev.blob_key)
            except _STORAGE_ERRORS:
                db.rollback()
                return "storage_down"
            except ValueError:
                db.rollback()
                log.error("retention: evidence has an invalid storage key (code=INVALID_BLOB_KEY)")
                return "failed"
            ev.upload_status, ev.deleted_at_utc = "DELETED", utcnow()
            db.commit()
            return "purged"
        except SQLAlchemyError as exc:
            db.rollback()
            log.error("retention: database error while purging evidence (type=%s)", type(exc).__name__)
            return "failed"


@dataclass
class _PhaseResult:
    eligible: int = 0
    purged: int = 0
    deferred: int = 0
    failed: int = 0
    storage_aborted: bool = False


def _execute(items: list[Item], purge: Callable[[uuid.UUID, uuid.UUID], Outcome], dry_run: bool) -> _PhaseResult:
    res = _PhaseResult(eligible=len(items))
    if dry_run:
        return res
    consecutive_storage_failures = 0
    for index, (item_id, parent_id) in enumerate(items):
        outcome = purge(item_id, parent_id)
        if outcome == "purged":
            res.purged += 1
            consecutive_storage_failures = 0
        elif outcome == "deferred":
            res.deferred += 1
        elif outcome == "storage_down":
            res.failed += 1
            consecutive_storage_failures += 1
            if consecutive_storage_failures >= STORAGE_BREAKER:
                res.storage_aborted = True
                res.deferred += len(items) - index - 1  # untouched; the next run retries them
                break
        else:
            res.failed += 1
            consecutive_storage_failures = 0
    return res


# ------------------------------------------------------------------------------------ orphan Blobs

def _aware(value: dt.datetime) -> dt.datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=dt.timezone.utc)


def _sweep_orphans(store: BlobStore, now: dt.datetime, dry_run: bool, summary: CleanupSummary) -> None:
    cutoff = now - ORPHAN_MIN_AGE
    candidates: list[str] = []
    try:
        # Materialise first: deleting while a directory/listing iterator is open is not reliable on every store.
        for info in store.list("attachments/"):
            summary.orphan_blobs_scanned += 1
            if _aware(info.last_modified) > cutoff:
                continue  # younger than 24 h: may be an upload whose SQL row is not committed yet
            try:
                validate_key(info.key)
            except ValueError:
                summary.foreign_blobs_ignored += 1  # not one of ours; never touch it
                continue
            candidates.append(info.key)
    except _STORAGE_ERRORS:
        summary.phase_errors.append("ORPHAN_SCAN_STORAGE_UNAVAILABLE")
        return

    consecutive = 0
    for start in range(0, len(candidates), ORPHAN_CHECK_CHUNK):
        chunk = candidates[start:start + ORPHAN_CHECK_CHUNK]
        try:
            with get_sessionmaker()() as db:
                known = set(db.scalars(select(Attachment.blob_key).where(Attachment.blob_key.in_(chunk))))
                known |= set(db.scalars(select(ClaimEvidence.blob_key).where(ClaimEvidence.blob_key.in_(chunk))))
        except SQLAlchemyError as exc:
            log.error("retention: database error during orphan check (type=%s)", type(exc).__name__)
            summary.phase_errors.append("ORPHAN_CHECK_DATABASE_ERROR")
            return
        orphans = [k for k in chunk if k not in known]
        summary.orphan_blobs_eligible += len(orphans)
        if dry_run:
            continue
        for key in orphans:
            try:
                store.delete(key)
            except _STORAGE_ERRORS:
                summary.orphan_blobs_failed += 1
                consecutive += 1
                if consecutive >= STORAGE_BREAKER:
                    summary.phase_errors.append("ORPHAN_SWEEP_STORAGE_UNAVAILABLE")
                    return
                continue
            summary.orphan_blobs_removed += 1
            consecutive = 0


# ------------------------------------------------------------------------------------ activity logs

def _purge_activity_logs(now: dt.datetime, dry_run: bool, summary: CleanupSummary) -> None:
    cutoff = now - ACTIVITY_LOG_RETENTION
    try:
        if dry_run:
            with get_sessionmaker()() as db:
                summary.activity_logs_eligible = int(
                    db.scalar(select(func.count()).select_from(ActivityLog).where(ActivityLog.created_at_utc < cutoff)) or 0
                )
            return
        while True:  # small batches keep locks short; each batch commits on its own
            with get_sessionmaker()() as db:
                batch = select(ActivityLog.activity_id).where(ActivityLog.created_at_utc < cutoff).limit(LOG_BATCH)
                result = db.execute(delete(ActivityLog).where(ActivityLog.activity_id.in_(batch)))
                removed = int(getattr(result, "rowcount", 0) or 0)
                db.commit()
            summary.activity_logs_purged += removed
            summary.activity_logs_eligible += removed
            if removed < LOG_BATCH:
                return
    except SQLAlchemyError as exc:
        log.error("retention: database error while purging activity logs (type=%s)", type(exc).__name__)
        summary.phase_errors.append("ACTIVITY_LOG_PURGE_DATABASE_ERROR")


# ------------------------------------------------------------------------------------ entry point

def _record_audit(summary: CleanupSummary, correlation_id: str) -> None:
    outcome = "SUCCESS" if summary.failures == 0 else "FAILURE"
    try:
        with get_sessionmaker()() as db:
            audit.log_event(
                db, event_type="RETENTION_CLEANUP", outcome=outcome, correlation_id=correlation_id,
                metadata={
                    "purged_attachments": summary.attachments_purged, "purged_evidence": summary.evidence_purged,
                    "purged_logs": summary.activity_logs_purged, "orphan_blobs_removed": summary.orphan_blobs_removed,
                    "failures": summary.failures, "operator": OPERATOR,
                },
            )
            db.commit()
        summary.audit_recorded = True
    except SQLAlchemyError as exc:
        log.error("retention: could not record the audit event (type=%s)", type(exc).__name__)


def run_retention_cleanup(*, store: BlobStore | None = None, now: dt.datetime | None = None,
                          dry_run: bool = False) -> CleanupSummary:
    """Execute every eligible retention action. Idempotent: a second run finds nothing left to do.

    `store` and `now` are injectable so tests use a controlled store and a controlled clock. `dry_run` only counts.
    """
    now = now or utcnow()
    summary = CleanupSummary(dry_run=dry_run)
    correlation_id = f"retention-{uuid.uuid4()}"

    resolved: BlobStore | None = store
    if resolved is None:
        try:
            resolved = get_blob_store()
        except AppError:
            summary.phase_errors.append("STORAGE_NOT_CONFIGURED")

    if resolved is not None:
        with get_sessionmaker()() as db:
            attachment_items = _eligible_attachments(db, now)
            evidence_items = _eligible_evidence(db, now)

        photos = _execute(attachment_items, functools.partial(_purge_attachment, resolved, now), dry_run)
        summary.attachments_eligible, summary.attachments_purged = photos.eligible, photos.purged
        summary.attachments_deferred, summary.attachments_failed = photos.deferred, photos.failed
        if photos.storage_aborted:
            summary.phase_errors.append("ATTACHMENT_PURGE_STORAGE_UNAVAILABLE")

        evidence = _execute(evidence_items, functools.partial(_purge_evidence, resolved, now), dry_run)
        summary.evidence_eligible, summary.evidence_purged = evidence.eligible, evidence.purged
        summary.evidence_deferred, summary.evidence_failed = evidence.deferred, evidence.failed
        if evidence.storage_aborted:
            summary.phase_errors.append("EVIDENCE_PURGE_STORAGE_UNAVAILABLE")

        _sweep_orphans(resolved, now, dry_run, summary)

    _purge_activity_logs(now, dry_run, summary)  # independent of Blob storage, so it still runs when storage is down

    if not dry_run:
        _record_audit(summary, correlation_id)  # written last, so this run's own event is never purged by it
    log.info(
        "retention run finished dry_run=%s attachments=%d evidence=%d orphans=%d logs=%d failures=%d", dry_run,
        summary.attachments_purged, summary.evidence_purged, summary.orphan_blobs_removed, summary.activity_logs_purged,
        summary.failures,
    )
    return summary
