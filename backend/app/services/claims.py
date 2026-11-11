"""Claims, verification, recovery and recovery void (contract §4.4, §17, §18, §24).

Lock order in every workflow: reports (ascending id) -> claims (ascending id) -> recoveries (ascending id).
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import conflict, forbidden, not_found, unprocessable
from app.core.security import new_id, utcnow
from app.core.text import clean_optional_note, clean_text
from app.persistence.models import Category, Claim, ClaimEvidence, ClaimStatusHistory, Location, Recovery, Report, User
from app.services import audit, retention
from app.services.auth import AuthContext
from app.services.locking import lock_claims, lock_recoveries, lock_reports
from app.services.matching_state import on_matching_relevant_change
from app.services.reports import iso, transition_report

REJECT_REASONS = {"INSUFFICIENT_EVIDENCE", "OWNERSHIP_NOT_CONFIRMED", "DUPLICATE_CLAIM", "OTHER"}
SYSTEM_NOTE = "A competing claim completed recovery."
LIVE = ("PENDING", "VERIFIED")
HOLDS_ITEM = ("VERIFIED", "RECOVERED")


# ------------------------------------------------------------------------- DTOs

def _report_ref(r: Report | None) -> dict | None:
    return None if r is None else {"report_id": str(r.report_id), "title": r.title, "status": r.status}


def active_evidence(db: Session, claim_id: uuid.UUID) -> list[ClaimEvidence]:
    return list(db.scalars(
        select(ClaimEvidence).where(ClaimEvidence.claim_id == claim_id, ClaimEvidence.upload_status == "ACTIVE",
                                    ClaimEvidence.deleted_at_utc.is_(None)).order_by(ClaimEvidence.uploaded_at_utc, ClaimEvidence.evidence_id)
    ))


def claim_dto(db: Session, c: Claim) -> dict:
    found = db.get(Report, c.found_report_id)
    lost = db.get(Report, c.lost_report_id) if c.lost_report_id else None
    return {
        "claim_id": str(c.claim_id), "found_report_id": str(c.found_report_id),
        "lost_report_id": str(c.lost_report_id) if c.lost_report_id else None,
        "claim_statement": c.claim_statement, "status": c.status, "version": c.version,
        "created_at_utc": iso(c.created_at_utc), "updated_at_utc": iso(c.updated_at_utc),
        "status_changed_at_utc": iso(c.status_changed_at_utc),
        "decision": {"reason_code": c.decision_reason_code, "decision_note": c.decision_note, "reviewed_at_utc": iso(c.reviewed_at_utc)},
        "information_request": {"note": c.information_request_note, "requested_at_utc": iso(c.information_requested_at_utc)},
        "evidence": [{"evidence_id": str(e.evidence_id), "content_type": e.content_type, "size_bytes": e.size_bytes,
                      "uploaded_at_utc": iso(e.uploaded_at_utc)} for e in active_evidence(db, c.claim_id)],
        "found_report": _report_ref(found), "lost_report": _report_ref(lost),
    }


def moderator_claim_dto(db: Session, c: Claim) -> dict:
    dto = claim_dto(db, c)
    claimant = db.get(User, c.claimant_user_id)
    reviewer = db.get(User, c.reviewed_by_user_id) if c.reviewed_by_user_id else None
    dto["claimant"] = {"user_id": str(claimant.user_id), "display_name": claimant.display_name, "email": claimant.email_normalized}
    dto["reviewer"] = {"user_id": str(reviewer.user_id), "display_name": reviewer.display_name} if reviewer else None
    dto["decision_note"] = c.decision_note
    hist = db.execute(
        select(ClaimStatusHistory, User.display_name)
        .outerjoin(User, User.user_id == ClaimStatusHistory.changed_by_user_id)
        .where(ClaimStatusHistory.claim_id == c.claim_id)
        .order_by(ClaimStatusHistory.changed_at_utc, ClaimStatusHistory.history_id)
    ).all()
    dto["history"] = [{"old_status": h.old_status, "new_status": h.new_status, "actor_display_name": name,
                       "reason_code": h.reason_code, "note": h.note, "changed_at_utc": iso(h.changed_at_utc)} for h, name in hist]
    dto["related_reports"] = {"found": _related(db, c.found_report_id), "lost": _related(db, c.lost_report_id) if c.lost_report_id else None}
    return dto


def _related(db: Session, report_id: uuid.UUID) -> dict:
    r = db.get(Report, report_id)
    cat = db.get(Category, r.category_id)
    loc = db.get(Location, r.location_id)
    owner = db.get(User, r.reporter_user_id)
    return {"report_id": str(r.report_id), "report_type": r.report_type, "title": r.title, "description": r.description,
            "category_name": cat.name, "location_name": loc.name, "occurred_on": r.occurred_on.isoformat(),
            "status": r.status, "version": r.version, "reporter": {"display_name": owner.display_name}}


def _snapshot(db: Session, found: Report, lost: Report | None) -> str:
    def safe(r: Report) -> dict:
        return {"report_id": str(r.report_id), "title": r.title, "description": r.description,
                "category_id": str(r.category_id), "location_id": str(r.location_id),
                "occurred_on": r.occurred_on.isoformat(), "status": r.status, "version": r.version}

    return json.dumps({"found": safe(found), "lost": safe(lost) if lost else None}, sort_keys=True)


# ------------------------------------------------------------------------- helpers

def _history(db: Session, claim: Claim, old: str, new: str, actor_id, reason: str, note: str | None, corr: str) -> None:
    db.add(ClaimStatusHistory(history_id=new_id(), claim_id=claim.claim_id, old_status=old, new_status=new,
                              changed_by_user_id=actor_id, changed_at_utc=utcnow(), reason_code=reason, note=note,
                              correlation_id=corr[:128]))


def _apply_status(db: Session, c: Claim, new: str, actor_id, reason: str, note: str | None, corr: str, *, review: bool = True,
                  system: bool = False) -> None:
    """Single place that changes a claim's status: bumps version once, writes history, sets decision fields."""
    now = utcnow()
    old = c.status
    c.status, c.version, c.updated_at_utc, c.status_changed_at_utc = new, c.version + 1, now, now
    if review:
        c.reviewed_by_user_id = None if system else actor_id
        c.reviewed_at_utc = now
        c.decision_reason_code = reason
        c.decision_note = note
    elif new in ("CANCELLED",):
        c.decision_reason_code, c.decision_note = reason, note
    _history(db, c, old, new, None if system else actor_id, reason, note, corr)
    db.flush()


def _expect(c: Claim, expected_version: int) -> None:
    if c.version != expected_version:
        raise conflict("VERSION_CONFLICT", "This claim was changed by someone else. Reload and try again.")


def _load_claim(db: Session, claim_id: uuid.UUID) -> Claim:
    c = db.get(Claim, claim_id)
    if c is None:
        raise not_found("Claim not found.")
    return c


def _lock_workflow(db: Session, claim_id: uuid.UUID, *, extra_report_ids=()) -> tuple[Claim, dict[uuid.UUID, Report]]:
    """Mandatory order: involved reports (sorted) first, then the claim row; re-validated under lock."""
    c = _load_claim(db, claim_id)
    reports = lock_reports(db, [c.found_report_id, c.lost_report_id, *extra_report_ids])
    claims = lock_claims(db, [claim_id])
    c = claims.get(claim_id)
    if c is None:
        raise not_found("Claim not found.")
    return c, reports


def _no_conflict_of_interest(ctx: AuthContext, c: Claim, found: Report) -> None:
    if ctx.user.user_id in (c.claimant_user_id, found.reporter_user_id):
        raise forbidden("A moderator cannot act on a claim they are involved in.", code="CONFLICT_OF_INTEREST")


# ------------------------------------------------------------------------- claimant workflows

def submit_claim(db: Session, ctx: AuthContext, found_report_id: uuid.UUID, *, claim_statement: str,
                 lost_report_id: uuid.UUID | None, corr: str) -> dict:
    if ctx.role != "STUDENT":
        raise forbidden("Only students can submit claims.")
    statement = clean_text(claim_statement, field="claim_statement", min_len=10, max_len=2000)
    locked = lock_reports(db, [found_report_id, lost_report_id])
    found = locked.get(found_report_id)
    if found is None or (found.status not in ("ACTIVE", "RESOLVED") and found.reporter_user_id != ctx.user.user_id):
        raise not_found("Report not found.")
    if found.reporter_user_id == ctx.user.user_id:
        raise forbidden("You cannot claim your own report.", code="SELF_CLAIM_FORBIDDEN")
    if found.report_type != "FOUND" or found.status != "ACTIVE":
        raise conflict("REPORT_NOT_ELIGIBLE", "This report is no longer eligible for this action.")
    lost = None
    if lost_report_id is not None:
        lost = locked.get(lost_report_id)
        if lost is None or lost.report_type != "LOST" or lost.reporter_user_id != ctx.user.user_id:
            raise unprocessable("Invalid linked report.", {"lost_report_id": ["Must be your own LOST report."]})
        if lost.status != "ACTIVE":
            raise unprocessable("Invalid linked report.", {"lost_report_id": ["The linked LOST report must be ACTIVE."]})
    if db.scalar(select(func.count()).select_from(Claim).where(Claim.found_report_id == found.report_id, Claim.status.in_(HOLDS_ITEM))):
        raise conflict("REPORT_NOT_ELIGIBLE", "This report is no longer eligible for this action.")
    if db.scalar(select(func.count()).select_from(Claim).where(
            Claim.found_report_id == found.report_id, Claim.claimant_user_id == ctx.user.user_id, Claim.status.in_(LIVE))):
        raise conflict("DUPLICATE_ACTIVE_CLAIM", "You already have an active claim on this report.")
    now = utcnow()
    claim = Claim(
        claim_id=new_id(), found_report_id=found.report_id, claimant_user_id=ctx.user.user_id,
        lost_report_id=lost.report_id if lost else None, claim_statement=statement, status="PENDING", version=1,
        found_report_version_at_submission=found.version, lost_report_version_at_submission=lost.version if lost else None,
        report_snapshot=_snapshot(db, found, lost), created_at_utc=now, updated_at_utc=now, status_changed_at_utc=now,
    )
    try:
        with db.begin_nested():
            db.add(claim)
            db.flush()
    except IntegrityError:
        raise conflict("DUPLICATE_ACTIVE_CLAIM", "You already have an active claim on this report.") from None
    audit.log_event(db, event_type="CLAIM_SUBMITTED", outcome="SUCCESS", correlation_id=corr, actor_user_id=ctx.user.user_id,
                    target_type="CLAIM", target_id=claim.claim_id)
    return claim_dto(db, claim)


def list_my_claims(db: Session, ctx: AuthContext, page: int, page_size: int) -> dict:
    q = select(Claim).where(Claim.claimant_user_id == ctx.user.user_id)
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = db.scalars(q.order_by(Claim.created_at_utc.desc(), Claim.claim_id.asc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [claim_dto(db, c) for c in rows], "page": page, "page_size": page_size, "total": total}


def get_own_claim(db: Session, ctx: AuthContext, claim_id: uuid.UUID) -> dict:
    c = db.get(Claim, claim_id)
    if c is None or c.claimant_user_id != ctx.user.user_id:
        raise not_found("Claim not found.")
    return claim_dto(db, c)


def cancel_claim(db: Session, ctx: AuthContext, claim_id: uuid.UUID, expected_version: int, corr: str) -> dict:
    existing = _load_claim(db, claim_id)
    if existing.claimant_user_id != ctx.user.user_id:
        raise not_found("Claim not found.")
    c, _reports = _lock_workflow(db, claim_id)
    _expect(c, expected_version)
    if c.status not in LIVE:
        raise conflict("CLAIM_NOT_CANCELLABLE", "Only PENDING or VERIFIED claims can be cancelled.")
    _apply_status(db, c, "CANCELLED", ctx.user.user_id, "CLAIMANT_CANCELLED", None, corr, review=False)
    retention.schedule_purge_for_claim(db, c.claim_id, c.status_changed_at_utc)
    audit.log_event(db, event_type="CLAIM_CANCELLED", outcome="SUCCESS", correlation_id=corr, actor_user_id=ctx.user.user_id,
                    target_type="CLAIM", target_id=c.claim_id, metadata={"reason_code": "CLAIMANT_CANCELLED"})
    return claim_dto(db, c)


# ------------------------------------------------------------------------- moderator reads

def moderator_list(db: Session, status: str | None, page: int, page_size: int) -> dict:
    if status not in (None, "PENDING", "VERIFIED", "RECOVERED", "REJECTED", "CANCELLED"):
        raise unprocessable("Invalid filter.", {"status": ["Invalid status."]})
    q = select(Claim)
    if status:
        q = q.where(Claim.status == status)
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = db.scalars(q.order_by(Claim.created_at_utc.desc(), Claim.claim_id.asc()).offset((page - 1) * page_size).limit(page_size)).all()
    items = []
    for c in rows:
        claimant = db.get(User, c.claimant_user_id)
        found = db.get(Report, c.found_report_id)
        items.append({"claim_id": str(c.claim_id), "status": c.status, "version": c.version,
                      "created_at_utc": iso(c.created_at_utc), "status_changed_at_utc": iso(c.status_changed_at_utc),
                      "claimant": {"display_name": claimant.display_name}, "found_report": _report_ref(found),
                      "has_linked_lost_report": c.lost_report_id is not None,
                      "evidence_count": len(active_evidence(db, c.claim_id))})
    return {"items": items, "page": page, "page_size": page_size, "total": total}


def moderator_detail(db: Session, ctx: AuthContext, claim_id: uuid.UUID, corr: str) -> dict:
    c = _load_claim(db, claim_id)
    audit.log_event(db, event_type="MODERATOR_CLAIM_DETAIL_ACCESSED", outcome="SUCCESS", correlation_id=corr,
                    actor_user_id=ctx.user.user_id, target_type="CLAIM", target_id=c.claim_id)
    return moderator_claim_dto(db, c)


# ------------------------------------------------------------------------- moderator decisions

def verify_claim(db: Session, ctx: AuthContext, claim_id: uuid.UUID, decision_note: str | None, expected_version: int, corr: str) -> dict:
    note = clean_optional_note(decision_note)
    c, reports = _lock_workflow(db, claim_id)
    _expect(c, expected_version)
    found, lost = reports[c.found_report_id], reports.get(c.lost_report_id) if c.lost_report_id else None
    _no_conflict_of_interest(ctx, c, found)
    if c.status != "PENDING":
        raise conflict("CLAIM_NOT_PENDING", "Only PENDING claims can be verified.")
    if found.status != "ACTIVE" or (lost is not None and (lost.status != "ACTIVE" or lost.reporter_user_id != c.claimant_user_id)):
        raise conflict("REPORT_NOT_ELIGIBLE", "A related report is no longer eligible.")
    holders = select(func.count()).select_from(Claim).where(Claim.claim_id != c.claim_id, Claim.status.in_(HOLDS_ITEM))
    if db.scalar(holders.where(Claim.found_report_id == found.report_id)) or (
            lost is not None and db.scalar(holders.where(Claim.lost_report_id == lost.report_id))):
        raise conflict("CLAIM_CONFLICT", "Another claim has already been verified for this item.")
    try:
        with db.begin_nested():
            _apply_status(db, c, "VERIFIED", ctx.user.user_id, "OWNERSHIP_CONFIRMED", note, corr)
    except IntegrityError:
        raise conflict("CLAIM_CONFLICT", "Another claim has already been verified for this item.") from None
    audit.log_event(db, event_type="CLAIM_VERIFIED", outcome="SUCCESS", correlation_id=corr, actor_user_id=ctx.user.user_id,
                    target_type="CLAIM", target_id=c.claim_id, metadata={"reason_code": "OWNERSHIP_CONFIRMED"})
    return claim_dto(db, c)


def reject_claim(db: Session, ctx: AuthContext, claim_id: uuid.UUID, reason_code: str, decision_note: str | None,
                 expected_version: int, corr: str) -> dict:
    if reason_code not in REJECT_REASONS:
        raise unprocessable("Invalid reason.", {"reason_code": ["Not an allowed rejection reason."]})
    note = clean_optional_note(decision_note)
    if reason_code == "OTHER" and not note:
        raise unprocessable("A note is required.", {"decision_note": ["Required when the reason is OTHER."]})
    c, reports = _lock_workflow(db, claim_id)
    _expect(c, expected_version)
    _no_conflict_of_interest(ctx, c, reports[c.found_report_id])
    if c.status != "PENDING":
        raise conflict("CLAIM_NOT_PENDING", "Only PENDING claims can be rejected.")
    _apply_status(db, c, "REJECTED", ctx.user.user_id, reason_code, note, corr)
    retention.schedule_purge_for_claim(db, c.claim_id, c.status_changed_at_utc)
    audit.log_event(db, event_type="CLAIM_REJECTED", outcome="SUCCESS", correlation_id=corr, actor_user_id=ctx.user.user_id,
                    target_type="CLAIM", target_id=c.claim_id, metadata={"reason_code": reason_code})
    return claim_dto(db, c)


def revoke_verification(db: Session, ctx: AuthContext, claim_id: uuid.UUID, decision_note: str | None, expected_version: int,
                        corr: str) -> dict:
    note = clean_optional_note(decision_note)
    c, reports = _lock_workflow(db, claim_id)
    _expect(c, expected_version)
    _no_conflict_of_interest(ctx, c, reports[c.found_report_id])
    if c.status != "VERIFIED":
        raise conflict("CLAIM_NOT_VERIFIED", "Only VERIFIED claims can have their verification revoked.")
    _apply_status(db, c, "REJECTED", ctx.user.user_id, "VERIFICATION_REVOKED", note, corr)
    retention.schedule_purge_for_claim(db, c.claim_id, c.status_changed_at_utc)
    audit.log_event(db, event_type="CLAIM_VERIFICATION_REVOKED", outcome="SUCCESS", correlation_id=corr,
                    actor_user_id=ctx.user.user_id, target_type="CLAIM", target_id=c.claim_id,
                    metadata={"reason_code": "VERIFICATION_REVOKED"})
    return claim_dto(db, c)


def request_information(db: Session, ctx: AuthContext, claim_id: uuid.UUID, decision_note: str, expected_version: int, corr: str) -> dict:
    note = clean_text(decision_note, field="decision_note", min_len=10, max_len=1000)
    c, reports = _lock_workflow(db, claim_id)
    _expect(c, expected_version)
    _no_conflict_of_interest(ctx, c, reports[c.found_report_id])
    if c.status != "PENDING":
        raise conflict("CLAIM_NOT_PENDING", "Information can only be requested on PENDING claims.")
    now = utcnow()
    c.information_request_note, c.information_requested_at_utc = note, now
    c.version, c.updated_at_utc = c.version + 1, now  # no status change; status_changed_at_utc untouched
    db.flush()
    audit.log_event(db, event_type="CLAIM_INFORMATION_REQUESTED", outcome="SUCCESS", correlation_id=corr,
                    actor_user_id=ctx.user.user_id, target_type="CLAIM", target_id=c.claim_id)  # note text never logged
    return claim_dto(db, c)


# ------------------------------------------------------------------------- recovery

def recovery_dto(rec: Recovery) -> dict:
    return {"recovery_id": str(rec.recovery_id), "claim_id": str(rec.claim_id), "found_report_id": str(rec.found_report_id),
            "lost_report_id": str(rec.lost_report_id) if rec.lost_report_id else None, "status": rec.status,
            "completed_at_utc": iso(rec.completed_at_utc), "voided_at_utc": iso(rec.voided_at_utc),
            "void_reason_code": rec.void_reason_code}


def complete_recovery(db: Session, ctx: AuthContext, claim_id: uuid.UUID, decision_note: str | None, expected_version: int,
                      corr: str) -> dict:
    note = clean_optional_note(decision_note)
    probe = _load_claim(db, claim_id)
    # Competing PENDING claims on the same FOUND report are part of this transaction's lock set.
    competitor_ids = [i for i in db.scalars(select(Claim.claim_id).where(
        Claim.found_report_id == probe.found_report_id, Claim.claim_id != claim_id, Claim.status == "PENDING"))]
    reports = lock_reports(db, [probe.found_report_id, probe.lost_report_id])
    claims = lock_claims(db, [claim_id, *competitor_ids])
    c = claims.get(claim_id)
    if c is None:
        raise not_found("Claim not found.")
    _expect(c, expected_version)
    found, lost = reports[c.found_report_id], reports.get(c.lost_report_id) if c.lost_report_id else None
    _no_conflict_of_interest(ctx, c, found)
    if c.status != "VERIFIED":
        raise conflict("CLAIM_NOT_VERIFIED", "Only VERIFIED claims can be recovered.")
    if found.status != "ACTIVE" or (lost is not None and lost.status != "ACTIVE"):
        raise conflict("REPORT_NOT_ELIGIBLE", "A related report is no longer eligible.")
    # Competitors may have changed since the unlocked read: recompute under lock.
    competitors = [x for x in claims.values() if x.claim_id != claim_id and x.status == "PENDING"]
    late = db.scalars(select(Claim.claim_id).where(Claim.found_report_id == found.report_id, Claim.claim_id != claim_id,
                                                   Claim.status == "PENDING", Claim.claim_id.notin_(list(claims)))).all()
    if late:
        competitors += list(lock_claims(db, late).values())

    now = utcnow()
    f_prior_status, f_prior_version = found.status, found.version
    l_prior_status, l_prior_version = (lost.status, lost.version) if lost else (None, None)
    for rep in (found, lost):
        if rep is not None:
            transition_report(db, rep, "RESOLVED", "RECOVERY_COMPLETED", ctx.user.user_id, corr)
            on_matching_relevant_change(db, rep, corr, ctx.user.user_id, "RECOVERY_COMPLETED")

    rec = Recovery(
        recovery_id=new_id(), claim_id=c.claim_id, found_report_id=found.report_id, lost_report_id=lost.report_id if lost else None,
        status="COMPLETED", completed_by_moderator_id=ctx.user.user_id, completed_at_utc=now,
        found_prior_status=f_prior_status, found_prior_version=f_prior_version, found_post_version=found.version,
        lost_prior_status=l_prior_status, lost_prior_version=l_prior_version, lost_post_version=lost.version if lost else None,
    )
    db.add(rec)
    # Recovery does not overwrite the claim's verification reviewer fields (contract §18).
    old = c.status
    c.status, c.version, c.updated_at_utc, c.status_changed_at_utc = "RECOVERED", c.version + 1, now, now
    _history(db, c, old, "RECOVERED", ctx.user.user_id, "RECOVERY_CONFIRMED", note, corr)
    retention.schedule_purge_for_claim(db, c.claim_id, now)
    for comp in sorted(competitors, key=lambda x: str(x.claim_id)):
        _apply_status(db, comp, "REJECTED", None, "OTHER_CLAIM_RECOVERED", SYSTEM_NOTE, corr, system=True)
        retention.schedule_purge_for_claim(db, comp.claim_id, now)
        audit.log_event(db, event_type="CLAIM_REJECTED", outcome="SYSTEM", correlation_id=corr, target_type="CLAIM",
                        target_id=comp.claim_id, metadata={"reason_code": "OTHER_CLAIM_RECOVERED"})
    db.flush()
    resolved = [found.report_id] + ([lost.report_id] if lost else [])
    audit.log_event(db, event_type="RECOVERY_COMPLETED", outcome="SUCCESS", correlation_id=corr, actor_user_id=ctx.user.user_id,
                    target_type="CLAIM", target_id=c.claim_id,
                    metadata={"recovery_id": rec.recovery_id, "resolved_reports": resolved,
                              "rejected_competing_claims": len(competitors)})
    return {"claim": claim_dto(db, c), "recovery": recovery_dto(rec), "resolved_reports": [str(i) for i in resolved]}


def void_recovery(db: Session, ctx: AuthContext, recovery_id: uuid.UUID, decision_note: str, expected_claim_version: int, corr: str) -> dict:
    note = clean_text(decision_note, field="decision_note", min_len=1, max_len=1000)
    rec0 = db.get(Recovery, recovery_id)
    if rec0 is None:
        raise not_found("Recovery not found.")
    reports = lock_reports(db, [rec0.found_report_id, rec0.lost_report_id])
    claim = lock_claims(db, [rec0.claim_id]).get(rec0.claim_id)
    rec = lock_recoveries(db, [recovery_id]).get(recovery_id)
    if rec is None or claim is None:
        raise not_found("Recovery not found.")
    _expect(claim, expected_claim_version)
    if rec.status != "COMPLETED" or claim.status != "RECOVERED":
        raise conflict("RECOVERY_NOT_VOIDABLE", "Only a completed recovery on a RECOVERED claim can be voided.")
    now = utcnow()
    rec.status, rec.voided_by_moderator_id, rec.voided_at_utc = "VOIDED", ctx.user.user_id, now
    rec.void_reason_code, rec.void_note = "RECOVERY_VOID", note
    old = claim.status
    claim.status, claim.version, claim.updated_at_utc, claim.status_changed_at_utc = "VERIFIED", claim.version + 1, now, now
    _history(db, claim, old, "VERIFIED", ctx.user.user_id, "RECOVERY_VOID", note, corr)
    retention.cancel_purge_for_claim(db, claim.claim_id)
    reopened: list[uuid.UUID] = []
    reconcile: list[uuid.UUID] = []
    for rid, post_version in ((rec.found_report_id, rec.found_post_version), (rec.lost_report_id, rec.lost_post_version)):
        if rid is None:
            continue
        rep = reports[rid]
        if rep.status == "RESOLVED" and rep.version == post_version:  # untouched since recovery -> safe to reopen
            transition_report(db, rep, "ACTIVE", "RECOVERY_VOID", ctx.user.user_id, corr)
            on_matching_relevant_change(db, rep, corr, ctx.user.user_id, "RECOVERY_VOID")
            reopened.append(rid)
        else:
            reconcile.append(rid)
    db.flush()
    audit.log_event(db, event_type="RECOVERY_VOIDED", outcome="SUCCESS", correlation_id=corr, actor_user_id=ctx.user.user_id,
                    target_type="CLAIM", target_id=claim.claim_id,
                    metadata={"recovery_id": recovery_id, "reopened_reports": reopened, "reports_requiring_reconciliation": reconcile})
    return {"claim": claim_dto(db, claim), "recovery": recovery_dto(rec), "reopened_reports": [str(i) for i in reopened],
            "reports_requiring_reconciliation": [str(i) for i in reconcile]}


_: Any = None
