"""Matching worker (Blueprint §6, contract §8, §11, §21, §24).

Flow per job: (1) lease in a short transaction and commit; (2) read the target + candidates and score
without holding job locks; (3) in a separate transaction lock all involved reports in global order,
re-verify versions, upsert matches and mark the job SUCCEEDED. Failures never roll back report writes.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import threading
import uuid
from decimal import Decimal

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import new_id, utcnow
from app.domain import matching as m
from app.persistence.database import get_sessionmaker
from app.persistence.models import Location, Match, MatchingJob, Report
from app.services import audit
from app.services.locking import lock_reports

log = logging.getLogger("findmything.matching")

LEASE = dt.timedelta(minutes=2)
MAX_ATTEMPTS = 8


def retry_delay_seconds(job_id: uuid.UUID, failure_number: int) -> float:
    """min(2^N, 3600) plus deterministic UUID-derived jitter of 0-15% (contract §21)."""
    base = min(2**failure_number, 3600)
    jitter = (job_id.int % 1501) / 10000  # 0.0000 .. 0.1500
    return base * (1 + jitter)


def lease_next_job(db: Session, now: dt.datetime | None = None) -> uuid.UUID | None:
    """Atomically lease one due job (multi-instance safe via READPAST); commits before returning."""
    now = now or utcnow()
    naive = now.replace(tzinfo=None)
    row = db.execute(
        text(
            "WITH next_job AS (SELECT TOP (1) * FROM matching_jobs WITH (UPDLOCK, READPAST, ROWLOCK) "
            "WHERE (status='PENDING' AND next_attempt_at_utc <= :now) OR (status='PROCESSING' AND lease_expires_at_utc <= :now) "
            "ORDER BY COALESCE(next_attempt_at_utc, lease_expires_at_utc), job_id) "
            "UPDATE next_job SET status='PROCESSING', lease_expires_at_utc=:lease, updated_at_utc=:now "
            "OUTPUT inserted.job_id"
        ),
        {"now": naive, "lease": (now + LEASE).replace(tzinfo=None)},
    ).first()
    db.commit()
    return uuid.UUID(str(row[0])) if row else None


def _view(db: Session, report_id_or_row) -> m.ReportView:
    r = report_id_or_row
    loc = db.get(Location, r.location_id)
    return m.ReportView(
        report_id=r.report_id, category_id=r.category_id, location_id=r.location_id,
        zone_id=loc.zone_id or loc.location_id, occurred_on=r.occurred_on, title=r.title,
        description=r.description, created_at_utc=r.created_at_utc,
    )


def _finish_job(db: Session, job: MatchingJob, status: str, error: str | None = None) -> None:
    job.status = status
    job.lease_expires_at_utc = None
    job.last_error_code = error
    job.updated_at_utc = utcnow()


def process_job(job_id: uuid.UUID) -> str:
    """Process a leased job. Returns the resulting job status."""
    SessionLocal = get_sessionmaker()
    algo = get_settings().algorithm_version
    try:
        # ---- phase 1: read target + candidates (no locks) -------------------------------
        with SessionLocal() as db:
            job = db.get(MatchingJob, job_id)
            if job is None or job.status != "PROCESSING":
                return "SKIPPED"
            target = db.get(Report, job.report_id)
            if target is None or target.status != "ACTIVE":
                _finish_job(db, job, "SUPERSEDED")
                db.commit()
                return "SUPERSEDED"
            if target.matching_version != job.report_matching_version:
                _finish_job(db, job, "SUPERSEDED")
                from app.services.matching_state import enqueue_job

                enqueue_job(db, target, f"job-{job_id}")  # process the current version instead
                db.commit()
                return "SUPERSEDED"
            target_version = target.matching_version
            target_view = _view(db, target)
            opposite = "FOUND" if target.report_type == "LOST" else "LOST"
            window = dt.timedelta(days=m.DATE_WINDOW_DAYS)
            cands = db.scalars(
                select(Report).where(
                    Report.report_type == opposite, Report.status == "ACTIVE", Report.report_id != target.report_id,
                    Report.occurred_on >= target.occurred_on - window, Report.occurred_on <= target.occurred_on + window,
                )
            ).all()
            snapshot = {c.report_id: (c.matching_version, _view(db, c)) for c in cands}
            is_lost = target.report_type == "LOST"
            target_id = target.report_id

        scored: dict[uuid.UUID, tuple[int, m.MatchResult]] = {}
        for cid, (cver, cview) in snapshot.items():
            lost, found = (target_view, cview) if is_lost else (cview, target_view)
            if m.in_candidate_window(lost, found):
                scored[cid] = (cver, m.score_pair(lost, found))

        # ---- phase 2: lock involved reports in global order, re-verify, write -------------
        with SessionLocal() as db:
            job = db.get(MatchingJob, job_id)
            if job is None or job.status != "PROCESSING":
                return "SKIPPED"
            locked = lock_reports(db, [target_id, *scored.keys()])
            t = locked.get(target_id)
            if t is None or t.status != "ACTIVE" or t.matching_version != target_version:
                _finish_job(db, job, "SUPERSEDED")
                db.commit()
                return "SUPERSEDED"
            potential = 0
            written = 0
            now = utcnow()
            for cid, (cver, res) in scored.items():
                c = locked.get(cid)
                if c is None or c.status != "ACTIVE" or c.matching_version != cver:
                    continue  # candidate changed meanwhile; its own job will score it
                lost_id, found_id = (target_id, cid) if is_lost else (cid, target_id)
                lost_ver, found_ver = (target_version, cver) if is_lost else (cver, target_version)
                written += 1
                potential += 1 if res.status == "POTENTIAL" else 0
                _upsert_match(db, lost_id, found_id, lost_ver, found_ver, res, algo, now, f"job-{job_id}")
            _finish_job(db, job, "SUCCEEDED")
            audit.log_event(db, event_type="MATCH_JOB_SUCCEEDED", outcome="SYSTEM", correlation_id=f"job-{job_id}",
                            target_type="REPORT", target_id=target_id,
                            metadata={"job_id": job_id, "candidate_count": written, "potential_count": potential,
                                      "algorithm_version": algo, "matching_version": target_version})
            db.commit()
            return "SUCCEEDED"
    except Exception as exc:
        log.exception("matching job failed job_id=%s", job_id)
        return _record_failure(job_id, type(exc).__name__)


def _upsert_match(db: Session, lost_id, found_id, lost_ver, found_ver, res: m.MatchResult, algo, now, correlation) -> None:
    existing = db.scalar(select(Match).where(
        Match.lost_report_id == lost_id, Match.found_report_id == found_id, Match.algorithm_version == algo,
    ).with_hint(Match, "WITH (UPDLOCK, HOLDLOCK)", "mssql"))
    explanation = json.dumps(res.explanation, sort_keys=True)
    if existing is None:
        db.add(Match(
            match_id=new_id(), lost_report_id=lost_id, found_report_id=found_id, score=res.total,
            category_score=res.category, location_score=res.location, date_score=res.date, keyword_score=res.keywords,
            explanation=explanation, algorithm_version=algo, calculated_at_utc=now, lost_report_matching_version=lost_ver,
            found_report_matching_version=found_ver, match_status=res.status,
        ))
        return
    versions_same = existing.lost_report_matching_version == lost_ver and existing.found_report_matching_version == found_ver
    if existing.match_status == "DISMISSED" and versions_same:
        return  # dismissal persists for the same matching versions and algorithm (contract §8)
    changed = (Decimal(existing.score) != res.total or existing.match_status != res.status or not versions_same)
    if changed:  # preserve the prior calculation snapshot in the audit trail (no personal data)
        audit.log_event(db, event_type="MATCH_JOB_SUCCEEDED", outcome="SYSTEM", correlation_id=correlation,
                        target_type="MATCH", target_id=existing.match_id,
                        metadata={"old_score": float(existing.score), "old_match_status": existing.match_status,
                                  "old_factors": {"category": float(existing.category_score), "location": float(existing.location_score),
                                                  "date": float(existing.date_score), "keywords": float(existing.keyword_score)},
                                  "old_lost_matching_version": existing.lost_report_matching_version,
                                  "old_found_matching_version": existing.found_report_matching_version})
    existing.score, existing.category_score, existing.location_score = res.total, res.category, res.location
    existing.date_score, existing.keyword_score = res.date, res.keywords
    existing.explanation, existing.calculated_at_utc = explanation, now
    existing.lost_report_matching_version, existing.found_report_matching_version = lost_ver, found_ver
    existing.match_status = res.status
    existing.invalidated_at_utc = None
    existing.invalidation_reason = None


def _record_failure(job_id: uuid.UUID, error_name: str) -> str:
    with get_sessionmaker()() as db:
        job = db.get(MatchingJob, job_id)
        if job is None:
            return "SKIPPED"
        job.attempt_count += 1
        code = ("ERR_" + "".join(ch for ch in error_name if ch.isalnum() or ch == "_"))[:64]
        job.last_error_code = code
        job.lease_expires_at_utc = None
        job.updated_at_utc = utcnow()
        if job.attempt_count >= MAX_ATTEMPTS:
            job.status = "DEAD"
            job.next_attempt_at_utc = None
            event = "MATCH_JOB_FAILED"
        else:
            job.status = "PENDING"
            job.next_attempt_at_utc = utcnow() + dt.timedelta(seconds=retry_delay_seconds(job_id, job.attempt_count))
            event = "MATCH_JOB_FAILED"
        audit.log_event(db, event_type=event, outcome="FAILURE", correlation_id=f"job-{job_id}", target_type="REPORT",
                        target_id=job.report_id,
                        metadata={"job_id": job_id, "attempt_count": job.attempt_count, "error_code": code, "status": job.status})
        status = job.status
        db.commit()
        return status


def run_due_jobs(max_jobs: int = 25) -> int:
    """Lease and process due jobs. Safe to call from any number of instances. Returns jobs handled."""
    handled = 0
    for _ in range(max_jobs):
        with get_sessionmaker()() as db:
            job_id = lease_next_job(db)
        if job_id is None:
            break
        process_job(job_id)
        handled += 1
    return handled


class MatchingPoller:
    """Background poller so pending jobs resume after restarts (Blueprint §6.1). Not needed for correctness."""

    def __init__(self, interval_seconds: float = 2.0) -> None:
        self.interval = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="matching-poller", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                run_due_jobs()
            except Exception:
                log.exception("matching poller iteration failed")
            self._stop.wait(self.interval)


_ = func
