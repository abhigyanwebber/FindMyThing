"""Report workflows (contract §2-§4.2, §8, §17, §24)."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import and_, case, exists, func, or_, select
from sqlalchemy.orm import Session, aliased

from app.core.config import get_campus_config
from app.core.errors import AppError, conflict, forbidden, not_found, unprocessable
from app.core.security import utcnow
from app.core.text import clean_optional_note, clean_text, validate_occurred_on
from app.persistence.database import set_trigger_context
from app.persistence.models import Attachment, Category, Claim, Location, Report, User
from app.services import audit
from app.services.auth import AuthContext
from app.services.locking import lock_reports
from app.services.matching_state import on_matching_relevant_change

CLOSE_REASONS = {"INVALID_REPORT", "DUPLICATE_REPORT", "INAPPROPRIATE_CONTENT", "ADMINISTRATIVE_CLOSURE", "OTHER"}
TERMINAL = ("RESOLVED", "WITHDRAWN", "CLOSED")
ACTIVE_CLAIM_STATUSES = ("PENDING", "VERIFIED")
Zone = aliased(Location)


def iso(value: dt.datetime | None) -> str | None:
    return value.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z" if value else None


def exists_flag(*conditions):
    """T-SQL has no SELECT EXISTS(...); wrap in CASE WHEN EXISTS THEN 1 ELSE 0."""
    return case((exists().where(*conditions), 1), else_=0)


def _has_photo():
    return exists_flag(
        Attachment.report_id == Report.report_id, Attachment.attachment_type == "REPORT_PHOTO",
        Attachment.upload_status == "ACTIVE", Attachment.deleted_at_utc.is_(None),
    )


def base_query():
    return (
        select(Report, Category.name, Location.location_id, Location.name, func.coalesce(Zone.name, Location.name),
               User.display_name, _has_photo().label("has_photo"))
        .join(Category, Category.category_id == Report.category_id)
        .join(Location, Location.location_id == Report.location_id)
        .outerjoin(Zone, Zone.location_id == Location.zone_id)
        .join(User, User.user_id == Report.reporter_user_id)
    )


def visible_clause(ctx: AuthContext):
    if ctx.is_moderator:
        return None
    return or_(Report.status.in_(("ACTIVE", "RESOLVED")), Report.reporter_user_id == ctx.user.user_id)


def to_dto(row, ctx: AuthContext, *, detail: bool = False, extras: dict[str, Any] | None = None) -> dict:
    r, cat_name, loc_id, loc_name, zone_name, reporter_name, has_photo = row
    dto: dict[str, Any] = {
        "report_id": str(r.report_id), "report_type": r.report_type,
        "category": {"category_id": str(r.category_id), "name": cat_name},
        "location": {"location_id": str(loc_id), "name": loc_name, "zone_name": zone_name},
        "title": r.title, "description": r.description, "occurred_on": r.occurred_on.isoformat(), "status": r.status,
        "reporter": {"display_name": reporter_name}, "created_at_utc": iso(r.created_at_utc),
        "updated_at_utc": iso(r.updated_at_utc), "status_changed_at_utc": iso(r.status_changed_at_utc),
        "version": r.version, "has_photo": bool(has_photo),
    }
    if ctx.is_moderator:
        dto["status_reason_code"] = r.status_reason_code
    if detail:
        dto.update(extras or {})
    return dto


def fetch_report_row(db: Session, report_id: uuid.UUID):
    return db.execute(base_query().where(Report.report_id == report_id)).first()


def get_visible_report(db: Session, ctx: AuthContext, report_id: uuid.UUID) -> Report:
    """Return the report if the actor may see it; otherwise 404 (deliberate concealment)."""
    r = db.get(Report, report_id)
    if r is None or (not ctx.is_moderator and r.status not in ("ACTIVE", "RESOLVED") and r.reporter_user_id != ctx.user.user_id):
        raise not_found("Report not found.")
    return r


def has_active_claim(db: Session, report_id: uuid.UUID) -> bool:
    return bool(db.scalar(select(exists_flag(
        or_(Claim.found_report_id == report_id, Claim.lost_report_id == report_id),
        Claim.status.in_(ACTIVE_CLAIM_STATUSES)))))


def _can_claim(db: Session, ctx: AuthContext, r: Report) -> bool:
    if ctx.role != "STUDENT" or r.report_type != "FOUND" or r.status != "ACTIVE" or r.reporter_user_id == ctx.user.user_id:
        return False
    blocked = db.scalar(select(exists_flag(Claim.found_report_id == r.report_id, Claim.status.in_(("VERIFIED", "RECOVERED")))))
    mine = db.scalar(select(exists_flag(Claim.found_report_id == r.report_id, Claim.claimant_user_id == ctx.user.user_id,
                                        Claim.status.in_(ACTIVE_CLAIM_STATUSES))))
    return not blocked and not mine


def report_detail(db: Session, ctx: AuthContext, report_id: uuid.UUID) -> dict:
    r = get_visible_report(db, ctx, report_id)
    row = fetch_report_row(db, r.report_id)
    is_owner = r.reporter_user_id == ctx.user.user_id
    extras: dict[str, Any] = {"is_owner": is_owner, "can_claim": _can_claim(db, ctx, r)}
    if is_owner:
        extras["claim_activity"] = {"has_active_claim": has_active_claim(db, r.report_id)}
    return to_dto(row, ctx, detail=True, extras=extras)


# ---------------------------------------------------------------- creation / listing

def _reference(db: Session, category_id: uuid.UUID, location_id: uuid.UUID) -> None:
    cat = db.get(Category, category_id)
    loc = db.get(Location, location_id)
    errors: dict[str, list[str]] = {}
    if cat is None or not cat.is_active:
        errors["category_id"] = ["Unknown or inactive category."]
    if loc is None or not loc.is_active:
        errors["location_id"] = ["Unknown or inactive location."]
    if errors:
        raise unprocessable("Invalid reference data.", errors)


def create_report(db: Session, ctx: AuthContext, *, report_type: str, category_id: uuid.UUID, location_id: uuid.UUID,
                  title: str, description: str, occurred_on: dt.date, correlation_id: str) -> dict:
    if ctx.role != "STUDENT":
        raise forbidden("Only students can create reports.")
    if report_type not in ("LOST", "FOUND"):
        raise unprocessable("Invalid report type.", {"report_type": ["Must be LOST or FOUND."]})
    title = clean_text(title, field="title", min_len=5, max_len=120)
    description = clean_text(description, field="description", min_len=10, max_len=2000)
    validate_occurred_on(occurred_on, get_campus_config()["timezone"])
    _reference(db, category_id, location_id)
    now = utcnow()
    r = Report(
        report_id=uuid.uuid4(), reporter_user_id=ctx.user.user_id, report_type=report_type, category_id=category_id,
        location_id=location_id, title=title, description=description, occurred_on=occurred_on, status="ACTIVE",
        status_changed_at_utc=now, created_at_utc=now, updated_at_utc=now, version=1, matching_version=1,
    )
    db.add(r)
    db.flush()
    audit.log_event(db, event_type="REPORT_CREATED", outcome="SUCCESS", correlation_id=correlation_id,
                    actor_user_id=ctx.user.user_id, target_type="REPORT", target_id=r.report_id,
                    metadata={"report_type": report_type})
    from app.services.matching_state import enqueue_job

    enqueue_job(db, r, correlation_id, ctx.user.user_id)
    return to_dto(fetch_report_row(db, r.report_id), ctx, detail=True, extras={"is_owner": True, "can_claim": False,
                  "claim_activity": {"has_active_claim": False}})


def _like(term: str) -> str:
    return "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_").replace("[", "\\[") + "%"


def list_reports(db: Session, ctx: AuthContext, *, report_type: str | None, status: str | None,
                 category_id: uuid.UUID | None, location_id: uuid.UUID | None, q: str | None, page: int,
                 page_size: int) -> dict:
    if report_type not in (None, "LOST", "FOUND"):
        raise unprocessable("Invalid filter.", {"type": ["Must be LOST or FOUND."]})
    if status not in (None, "ACTIVE", "RESOLVED", "WITHDRAWN", "CLOSED"):
        raise unprocessable("Invalid filter.", {"status": ["Invalid status."]})
    status = status or "ACTIVE"
    query = base_query().where(Report.status == status)
    if status in ("WITHDRAWN", "CLOSED") and not ctx.is_moderator:
        query = query.where(Report.reporter_user_id == ctx.user.user_id)
    if report_type:
        query = query.where(Report.report_type == report_type)
    if category_id:
        query = query.where(Report.category_id == category_id)
    if location_id:
        query = query.where(Report.location_id == location_id)
    if q:
        q = clean_text(q, field="q", min_len=1, max_len=100)
        for term in q.split(" ")[:8]:
            like = _like(term)
            query = query.where(or_(Report.title.like(like, escape="\\"), Report.description.like(like, escape="\\")))
    total = db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
    rows = db.execute(
        query.order_by(Report.created_at_utc.desc(), Report.report_id.asc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return {"items": [to_dto(r, ctx) for r in rows], "page": page, "page_size": page_size, "total": total or 0}


# ---------------------------------------------------------------- mutations

def _lock_for_mutation(db: Session, report_id: uuid.UUID, expected_version: int) -> Report:
    locked = lock_reports(db, [report_id])
    r = locked.get(report_id)
    if r is None:
        raise not_found("Report not found.")
    return r


def _check_version(r: Report, expected: int) -> None:
    if r.version != expected:
        raise conflict("VERSION_CONFLICT", "This report was changed by someone else. Reload and try again.")


def _bump(r: Report, *, matching: bool) -> None:
    r.version += 1
    if matching:
        r.matching_version += 1
    r.updated_at_utc = utcnow()


def update_report(db: Session, ctx: AuthContext, report_id: uuid.UUID, *, title: str | None, description: str | None,
                  occurred_on: dt.date | None, expected_version: int, correlation_id: str) -> dict:
    r = _lock_for_mutation(db, report_id, expected_version)
    if r.reporter_user_id != ctx.user.user_id:
        raise not_found("Report not found.") if r.status not in ("ACTIVE", "RESOLVED") else forbidden()
    _check_version(r, expected_version)
    if r.status != "ACTIVE":
        raise conflict("REPORT_NOT_ACTIVE", "Only ACTIVE reports can be edited.")
    if has_active_claim(db, r.report_id):
        raise conflict("ACTIVE_CLAIM_EXISTS", "This report cannot be edited while a claim is open.")
    changed = _apply_text_fields(r, title, description, occurred_on)
    if not changed:
        return to_dto(fetch_report_row(db, r.report_id), ctx, detail=True, extras={"is_owner": True, "can_claim": False,
                      "claim_activity": {"has_active_claim": False}})
    _bump(r, matching=True)
    db.flush()
    on_matching_relevant_change(db, r, correlation_id, ctx.user.user_id, "REPORT_EDITED")
    audit.log_event(db, event_type="REPORT_UPDATED", outcome="SUCCESS", correlation_id=correlation_id,
                    actor_user_id=ctx.user.user_id, target_type="REPORT", target_id=r.report_id,
                    metadata={"changed_fields": changed})
    return report_detail(db, ctx, r.report_id)


def _apply_text_fields(r: Report, title, description, occurred_on) -> list[str]:
    changed: list[str] = []
    if title is not None:
        t = clean_text(title, field="title", min_len=5, max_len=120)
        if t != r.title:
            r.title = t
            changed.append("title")
    if description is not None:
        d = clean_text(description, field="description", min_len=10, max_len=2000)
        if d != r.description:
            r.description = d
            changed.append("description")
    if occurred_on is not None:
        validate_occurred_on(occurred_on, get_campus_config()["timezone"])
        if occurred_on != r.occurred_on:
            r.occurred_on = occurred_on
            changed.append("occurred_on")
    return changed


def transition_report(db: Session, r: Report, new_status: str, reason: str, actor_id: uuid.UUID | None, correlation_id: str) -> None:
    """Apply a status change; the SQL trigger writes report_status_history from SESSION_CONTEXT (D-021)."""
    set_trigger_context(db, actor_id, reason, correlation_id)
    r.status = new_status
    r.status_reason_code = reason
    r.status_changed_at_utc = utcnow()
    _bump(r, matching=True)  # eligibility (ACTIVE vs not) is matching-relevant (contract §8)
    db.flush()
    from app.services import retention

    if new_status == "ACTIVE":
        retention.cancel_purge_for_report(db, r.report_id)
    else:
        retention.schedule_purge_for_report(db, r.report_id, r.status_changed_at_utc)


def withdraw_report(db: Session, ctx: AuthContext, report_id: uuid.UUID, *, expected_version: int, correlation_id: str) -> dict:
    r = _lock_for_mutation(db, report_id, expected_version)
    if r.reporter_user_id != ctx.user.user_id:
        raise not_found("Report not found.") if r.status not in ("ACTIVE", "RESOLVED") else forbidden()
    _check_version(r, expected_version)
    if r.status != "ACTIVE":
        raise conflict("REPORT_NOT_ACTIVE", "Only ACTIVE reports can be withdrawn.")
    if has_active_claim(db, r.report_id):
        raise conflict("ACTIVE_CLAIM_EXISTS", "This report cannot be withdrawn while a claim is open.")
    transition_report(db, r, "WITHDRAWN", "OWNER_WITHDRAWAL", ctx.user.user_id, correlation_id)
    on_matching_relevant_change(db, r, correlation_id, ctx.user.user_id, "REPORT_WITHDRAWN")
    audit.log_event(db, event_type="REPORT_WITHDRAWN", outcome="SUCCESS", correlation_id=correlation_id,
                    actor_user_id=ctx.user.user_id, target_type="REPORT", target_id=r.report_id,
                    metadata={"reason_code": "OWNER_WITHDRAWAL"})
    return report_detail(db, ctx, r.report_id)


def _require_note_for_other(reason: str, note: str | None) -> None:
    if reason == "OTHER" and not note:
        raise unprocessable("A note is required.", {"decision_note": ["Required when the reason is OTHER."]})


def close_report(db: Session, ctx: AuthContext, report_id: uuid.UUID, *, reason_code: str, decision_note: str | None,
                 expected_version: int, correlation_id: str) -> dict:
    if reason_code not in CLOSE_REASONS:
        raise unprocessable("Invalid reason.", {"reason_code": ["Not an allowed close reason."]})
    note = clean_optional_note(decision_note)
    _require_note_for_other(reason_code, note)
    r = _lock_for_mutation(db, report_id, expected_version)
    _check_version(r, expected_version)
    if r.status != "ACTIVE":
        raise conflict("REPORT_NOT_ACTIVE", "Only ACTIVE reports can be closed.")
    if has_active_claim(db, r.report_id):
        raise conflict("ACTIVE_CLAIM_EXISTS", "Terminalize related PENDING/VERIFIED claims before closing the report.")
    transition_report(db, r, "CLOSED", reason_code, ctx.user.user_id, correlation_id)
    on_matching_relevant_change(db, r, correlation_id, ctx.user.user_id, "REPORT_CLOSED")
    audit.log_event(db, event_type="REPORT_CLOSED", outcome="SUCCESS", correlation_id=correlation_id,
                    actor_user_id=ctx.user.user_id, target_type="REPORT", target_id=r.report_id,
                    metadata={"reason_code": reason_code, "decision_note": note})
    return report_detail(db, ctx, r.report_id)


def reopen_report(db: Session, ctx: AuthContext, report_id: uuid.UUID, *, decision_note: str | None, expected_version: int,
                  correlation_id: str) -> dict:
    note = clean_optional_note(decision_note)
    r = _lock_for_mutation(db, report_id, expected_version)
    _check_version(r, expected_version)
    if r.status not in ("WITHDRAWN", "CLOSED"):
        raise conflict("REPORT_NOT_REOPENABLE", "Only WITHDRAWN or CLOSED reports can be reopened.")
    transition_report(db, r, "ACTIVE", "MODERATOR_REOPEN", ctx.user.user_id, correlation_id)
    from app.services.retention import cancel_purge_for_report

    cancel_purge_for_report(db, r.report_id)
    on_matching_relevant_change(db, r, correlation_id, ctx.user.user_id, "REPORT_REOPENED")
    audit.log_event(db, event_type="REPORT_REOPENED", outcome="SUCCESS", correlation_id=correlation_id,
                    actor_user_id=ctx.user.user_id, target_type="REPORT", target_id=r.report_id,
                    metadata={"reason_code": "MODERATOR_REOPEN", "decision_note": note})
    return report_detail(db, ctx, r.report_id)


def moderator_correct(db: Session, ctx: AuthContext, report_id: uuid.UUID, *, title: str | None, description: str | None,
                      occurred_on: dt.date | None, category_id: uuid.UUID | None, location_id: uuid.UUID | None,
                      decision_note: str | None, expected_version: int, correlation_id: str) -> dict:
    note = clean_optional_note(decision_note)
    r = _lock_for_mutation(db, report_id, expected_version)
    _check_version(r, expected_version)
    changed = _apply_text_fields(r, title, description, occurred_on)
    if category_id is not None or location_id is not None:
        _reference(db, category_id or r.category_id, location_id or r.location_id)
        if category_id is not None and category_id != r.category_id:
            r.category_id = category_id
            changed.append("category_id")
        if location_id is not None and location_id != r.location_id:
            r.location_id = location_id
            changed.append("location_id")
    if not changed:
        raise unprocessable("Nothing to change.", {"request": ["No fields were changed."]})
    _bump(r, matching=True)
    db.flush()
    # Terminal reports: invalidate matches, never enqueue or change status (contract §4.2).
    on_matching_relevant_change(db, r, correlation_id, ctx.user.user_id, "MODERATOR_CORRECTION")
    audit.log_event(db, event_type="REPORT_MODERATOR_CORRECTED", outcome="SUCCESS", correlation_id=correlation_id,
                    actor_user_id=ctx.user.user_id, target_type="REPORT", target_id=r.report_id,
                    metadata={"reason_code": "MODERATOR_CORRECTION", "changed_fields": changed, "decision_note": note})
    return report_detail(db, ctx, r.report_id)


_ = (AppError, and_)
