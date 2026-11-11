"""Matching outbox + match invalidation, always called inside the owning domain transaction (contract §8, §11, §24)."""

from __future__ import annotations

import uuid

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import new_id, utcnow
from app.persistence.models import Match, MatchingJob, Report
from app.services import audit

OPEN_STATUSES = ("PENDING", "PROCESSING")


def invalidate_matches(db: Session, report_id: uuid.UUID, reason: str) -> int:
    """Mark every non-invalidated match involving the report INVALIDATED (matching_version changed)."""
    res = db.execute(
        update(Match)
        .where((Match.lost_report_id == report_id) | (Match.found_report_id == report_id), Match.match_status != "INVALIDATED")
        .values(match_status="INVALIDATED", invalidated_at_utc=utcnow(), invalidation_reason=reason[:64])
    )
    return res.rowcount or 0


def supersede_pending_jobs(db: Session, report_id: uuid.UUID, current_matching_version: int) -> None:
    """Jobs for older matching versions can never produce current matches."""
    db.execute(
        update(MatchingJob)
        .where(MatchingJob.report_id == report_id, MatchingJob.report_matching_version < current_matching_version,
               MatchingJob.status.in_(("PENDING",)))
        .values(status="SUPERSEDED", updated_at_utc=utcnow())
    )


def enqueue_job(db: Session, report: Report, correlation_id: str, actor_user_id: uuid.UUID | None = None) -> MatchingJob:
    """Insert (or requeue) the idempotent job for (report, matching_version, algorithm)."""
    algo = get_settings().algorithm_version
    now = utcnow()
    job = db.scalar(
        select(MatchingJob).where(
            MatchingJob.report_id == report.report_id, MatchingJob.report_matching_version == report.matching_version,
            MatchingJob.algorithm_version == algo,
        ).with_hint(MatchingJob, "WITH (UPDLOCK, HOLDLOCK)", "mssql")
    )
    if job is None:
        job = MatchingJob(
            job_id=new_id(), report_id=report.report_id, report_matching_version=report.matching_version,
            algorithm_version=algo, status="PENDING", attempt_count=0, next_attempt_at_utc=now,
            created_at_utc=now, updated_at_utc=now,
        )
        db.add(job)
    db.flush()
    audit.log_event(db, event_type="MATCH_JOB_QUEUED", outcome="SUCCESS", correlation_id=correlation_id,
                    actor_user_id=actor_user_id, target_type="REPORT", target_id=report.report_id,
                    metadata={"job_id": job.job_id, "matching_version": report.matching_version})
    return job


def on_matching_relevant_change(db: Session, report: Report, correlation_id: str, actor_user_id: uuid.UUID | None,
                                reason: str) -> None:
    """Invalidate matches and, only if the report is ACTIVE, enqueue matching (contract §4.2/§8)."""
    invalidate_matches(db, report.report_id, reason)
    supersede_pending_jobs(db, report.report_id, report.matching_version)
    if report.status == "ACTIVE":
        enqueue_job(db, report, correlation_id, actor_user_id)


_ = text
