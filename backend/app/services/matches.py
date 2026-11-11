"""Match listing, recalculation and dismissal (contract §4.3)."""

from __future__ import annotations

import json
import uuid
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, literal_column, select, update
from sqlalchemy.orm import Session, aliased

from app.core import ratelimit
from app.core.config import get_settings
from app.core.errors import conflict, forbidden, not_found, unprocessable
from app.core.security import utcnow
from app.core.text import clean_optional_note
from app.persistence.models import Category, Location, Match, MatchingJob, Report
from app.services import audit
from app.services.auth import AuthContext
from app.services.locking import lock_reports
from app.services.matching_state import enqueue_job
from app.services.reports import get_visible_report, iso

DISMISS_REASONS = {"INVALID_MATCH", "DUPLICATE_MATCH", "OTHER"}
RECALC_LIMIT, RECALC_WINDOW = 5, 3600


def disp(value) -> float:
    return float(Decimal(value).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def _factors(m: Match) -> dict:
    return {"category": disp(m.category_score), "location": disp(m.location_score),
            "date": disp(m.date_score), "keywords": disp(m.keyword_score)}


def _explanation(m: Match) -> dict:
    try:
        return json.loads(m.explanation)
    except ValueError:
        return {}


def list_matches(db: Session, ctx: AuthContext, report_id: uuid.UUID, page: int, page_size: int) -> dict:
    r = get_visible_report(db, ctx, report_id)
    if r.reporter_user_id != ctx.user.user_id and not ctx.is_moderator:
        raise forbidden()
    empty = {"items": [], "page": page, "page_size": page_size, "total": 0}
    if not ctx.is_moderator and r.status != "ACTIVE":
        return empty

    counter = aliased(Report)
    is_lost = r.report_type == "LOST"
    own_col, other_col = (Match.lost_report_id, Match.found_report_id) if is_lost else (Match.found_report_id, Match.lost_report_id)
    q = (
        select(Match, counter, Category.name, Location.name)
        .join(counter, counter.report_id == other_col)
        .join(Category, Category.category_id == counter.category_id)
        .join(Location, Location.location_id == counter.location_id)
        .where(own_col == r.report_id)
    )
    if not ctx.is_moderator:
        q = q.where(Match.match_status == "POTENTIAL")
    total = db.scalar(select(func.count()).select_from(q.order_by(None).subquery())) or 0
    gap = func.abs(func.datediff(literal_column("day"), counter.occurred_on, r.occurred_on))
    rows = db.execute(
        q.order_by(Match.score.desc(), gap.asc(), Match.location_score.desc(), counter.created_at_utc.asc(), counter.report_id.asc())
        .offset((page - 1) * page_size).limit(page_size)
    ).all()
    items = [
        {
            "match_id": str(m.match_id),
            "counterpart_report": {
                "report_id": str(c.report_id), "report_type": c.report_type, "title": c.title, "category_name": cat,
                "location_name": loc, "occurred_on": c.occurred_on.isoformat(), "status": c.status,
            },
            "score": disp(m.score), "factors": _factors(m), "explanation": _explanation(m),
            "calculated_at_utc": iso(m.calculated_at_utc), "algorithm_version": m.algorithm_version,
            "match_status": m.match_status,
        }
        for m, c, cat, loc in rows
    ]
    return {"items": items, "page": page, "page_size": page_size, "total": total}


def recalculate(db: Session, ctx: AuthContext, report_id: uuid.UUID, correlation_id: str) -> tuple[int, dict]:
    r = get_visible_report(db, ctx, report_id)
    if r.reporter_user_id != ctx.user.user_id and not ctx.is_moderator:
        raise forbidden()
    count, retry = ratelimit.increment(db, "match_recalc", f"{ctx.user.user_id}:{report_id}", RECALC_WINDOW)
    if count > RECALC_LIMIT:
        audit.log_event(db, event_type="RATE_LIMIT_TRIGGERED", outcome="DENIED", correlation_id=correlation_id,
                        actor_user_id=ctx.user.user_id, target_type="REPORT", target_id=report_id,
                        metadata={"limit_name": "match_recalc"})
        db.commit()
        raise ratelimit.throttled(retry)
    locked = lock_reports(db, [report_id]).get(report_id)
    if locked is None or locked.status != "ACTIVE":
        raise conflict("REPORT_NOT_ACTIVE", "Only ACTIVE reports can be recalculated.")
    algo = get_settings().algorithm_version
    job = db.scalar(select(MatchingJob).where(
        MatchingJob.report_id == report_id, MatchingJob.report_matching_version == locked.matching_version,
        MatchingJob.algorithm_version == algo).with_hint(MatchingJob, "WITH (UPDLOCK, HOLDLOCK)", "mssql"))
    if job is not None and job.status in ("PENDING", "PROCESSING"):
        return 200, {"job_id": str(job.job_id), "status": job.status}
    if job is None:
        job = enqueue_job(db, locked, correlation_id, ctx.user.user_id)
        return 202, {"job_id": str(job.job_id), "status": "PENDING"}
    now = utcnow()
    job.status, job.attempt_count, job.lease_expires_at_utc, job.last_error_code = "PENDING", 0, None, None
    job.next_attempt_at_utc, job.updated_at_utc = now, now
    db.flush()
    audit.log_event(db, event_type="MATCH_JOB_QUEUED", outcome="SUCCESS", correlation_id=correlation_id,
                    actor_user_id=ctx.user.user_id, target_type="REPORT", target_id=report_id,
                    metadata={"job_id": job.job_id, "matching_version": locked.matching_version})
    return 202, {"job_id": str(job.job_id), "status": "PENDING"}


def dismiss(db: Session, ctx: AuthContext, match_id: uuid.UUID, reason_code: str, decision_note: str | None,
            correlation_id: str) -> dict:
    if reason_code not in DISMISS_REASONS:
        raise unprocessable("Invalid reason.", {"reason_code": ["Not an allowed dismissal reason."]})
    note = clean_optional_note(decision_note)
    if reason_code == "OTHER" and not note:
        raise unprocessable("A note is required.", {"decision_note": ["Required when the reason is OTHER."]})
    m = db.get(Match, match_id)
    if m is None:
        raise not_found("Match not found.")
    lock_reports(db, [m.lost_report_id, m.found_report_id])  # global lock order before the match row
    res = db.execute(
        update(Match).where(Match.match_id == match_id, Match.match_status == "POTENTIAL").values(match_status="DISMISSED")
    )
    if not res.rowcount:
        raise conflict("MATCH_NOT_DISMISSABLE", "Only POTENTIAL matches can be dismissed.")
    audit.log_event(db, event_type="MATCH_DISMISSED", outcome="SUCCESS", correlation_id=correlation_id,
                    actor_user_id=ctx.user.user_id, target_type="MATCH", target_id=match_id,
                    metadata={"reason_code": reason_code, "decision_note": note})
    db.expire(m)
    m = db.get(Match, match_id)
    return {
        "match_id": str(m.match_id), "lost_report_id": str(m.lost_report_id), "found_report_id": str(m.found_report_id),
        "score": disp(m.score), "factors": _factors(m), "explanation": _explanation(m),
        "calculated_at_utc": iso(m.calculated_at_utc), "algorithm_version": m.algorithm_version, "match_status": m.match_status,
    }
