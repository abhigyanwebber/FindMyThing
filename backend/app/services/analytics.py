"""Moderator analytics summary and activity feed (contract 4.5, 19, 22; Blueprint 10).

Read-only. Only aggregates (analytics) or allowlisted audit fields (activity) are returned: never claim
statements, evidence, claimant identity, credentials, Blob keys or free-text notes other than moderator
report-action notes.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, Float, Integer, Subquery, case, cast, func, literal_column, select
from sqlalchemy.orm import InstrumentedAttribute, Session

from app.core.config import get_campus_config
from app.core.errors import unprocessable
from app.core.security import utcnow
from app.persistence.models import ActivityLog, Category, Claim, ClaimStatusHistory, Location, Recovery, Report, User
from app.services import audit
from app.services.reports import iso

DEFAULT_WINDOW_DAYS = 90
MAX_RANGE_DAYS = 366
REPORT_STATUSES = ("ACTIVE", "RESOLVED", "WITHDRAWN", "CLOSED")
CLAIM_TRANSITIONS = ("VERIFIED", "REJECTED", "CANCELLED")
MS_PER_DAY = 86_400_000.0

# `decision_note` is exposed only for moderator report actions (contract 4.5/5); never for other events.
REPORT_NOTE_EVENTS = frozenset({"REPORT_CLOSED", "REPORT_REOPENED", "REPORT_MODERATOR_CORRECTED"})


# ---- period handling -------------------------------------------------------------------------------------
def campus_tz() -> ZoneInfo:
    return ZoneInfo(get_campus_config()["timezone"])


def local_midnight_utc(day: dt.date, tz: ZoneInfo) -> dt.datetime:
    return dt.datetime.combine(day, dt.time.min, tzinfo=tz).astimezone(dt.timezone.utc)


def resolve_period(date_from: dt.date | None, date_to: dt.date | None, now: dt.datetime) -> tuple[dt.date, dt.date]:
    """Inclusive campus-local dates. Default: the last 90 days through today (contract 4.5)."""
    today = now.astimezone(campus_tz()).date()
    end = date_to or today
    start = date_from or (end - dt.timedelta(days=DEFAULT_WINDOW_DAYS - 1))
    if start > end:
        raise unprocessable("Invalid period.", {"from": ["'from' must not be after 'to'."]})
    if (end - start).days + 1 > MAX_RANGE_DAYS:
        raise unprocessable("Invalid period.", {"to": [f"The period must not exceed {MAX_RANGE_DAYS} days."]})
    return start, end


def _round1(value: float | None) -> float | None:
    if value is None:
        return None
    return float(Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def _pct(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return _round1(numerator * 100.0 / denominator)


def _months(start: dt.date, end: dt.date) -> list[dt.date]:
    months: list[dt.date] = []
    cur = dt.date(start.year, start.month, 1)
    while cur <= end:
        months.append(cur)
        cur = dt.date(cur.year + (cur.month == 12), cur.month % 12 + 1, 1)
    return months


# ---- analytics summary -----------------------------------------------------------------------------------
def analytics_summary(db: Session, date_from: dt.date | None, date_to: dt.date | None) -> dict[str, object]:
    as_of = utcnow()
    start, end = resolve_period(date_from, date_to, as_of)
    tz = campus_tz()
    start_utc = local_midnight_utc(start, tz)
    end_utc = local_midnight_utc(end + dt.timedelta(days=1), tz)  # exclusive upper bound

    cohort = (Report.created_at_utc >= start_utc, Report.created_at_utc < end_utc)
    is_found = Report.report_type == "FOUND"
    # One non-voided completed recovery per FOUND report (ux_rec_found), as of the snapshot instant.
    rec = (
        select(Recovery.found_report_id.label("report_id"), func.min(Recovery.completed_at_utc).label("completed_at"))
        .where(Recovery.status == "COMPLETED", Recovery.completed_at_utc <= as_of)
        .group_by(Recovery.found_report_id)
        .subquery()
    )

    # Report counts by type and current status (cohort = report creation date).
    status_counts: dict[str, dict[str, int]] = {"LOST": dict.fromkeys(REPORT_STATUSES, 0), "FOUND": dict.fromkeys(REPORT_STATUSES, 0)}
    for rtype, status, n in db.execute(
        select(Report.report_type, Report.status, func.count()).where(*cohort).group_by(Report.report_type, Report.status)
    ).all():
        status_counts[rtype][status] = n
    lost_total = sum(status_counts["LOST"].values())
    found_total = sum(status_counts["FOUND"].values())
    active_total = status_counts["LOST"]["ACTIVE"] + status_counts["FOUND"]["ACTIVE"]
    found_non_withdrawn = found_total - status_counts["FOUND"]["WITHDRAWN"]

    # Recovered FOUND reports in the cohort: numerator, average and median elapsed time (creation -> completed recovery).
    elapsed_ms = func.datediff_big(literal_column("millisecond"), Report.created_at_utc, rec.c.completed_at)
    recovered_n, avg_ms = db.execute(
        select(func.count(), func.avg(cast(elapsed_ms, Float))).select_from(Report).join(rec, rec.c.report_id == Report.report_id)
        .where(is_found, *cohort)
    ).one()
    median_ms: float | None = None
    if recovered_n:
        median_ms = db.execute(
            select(func.percentile_cont(literal_column("0.5")).within_group(elapsed_ms).over())
            .select_from(Report).join(rec, rec.c.report_id == Report.report_id).where(is_found, *cohort).limit(1)
        ).scalar_one()

    # Claims: submissions created in the period; verified/rejected/cancelled are transition EVENTS in the period.
    claims_submitted = db.execute(
        select(func.count()).select_from(Claim).where(Claim.created_at_utc >= start_utc, Claim.created_at_utc < end_utc)
    ).scalar_one()
    transitions = dict.fromkeys(CLAIM_TRANSITIONS, 0)
    for new_status, n in db.execute(
        select(ClaimStatusHistory.new_status, func.count())
        .where(ClaimStatusHistory.changed_at_utc >= start_utc, ClaimStatusHistory.changed_at_utc < end_utc,
               ClaimStatusHistory.new_status.in_(CLAIM_TRANSITIONS))
        .group_by(ClaimStatusHistory.new_status)
    ).all():
        transitions[new_status] = n

    # Completed, non-voided recoveries whose completion instant falls in the period (recovery-event view).
    recoveries_in_period = db.execute(
        select(func.count()).select_from(Recovery)
        .where(Recovery.status == "COMPLETED", Recovery.completed_at_utc >= start_utc, Recovery.completed_at_utc < end_utc,
               Recovery.completed_at_utc <= as_of)
    ).scalar_one()

    return {
        "period": {"from": start.isoformat(), "to": end.isoformat(), "as_of_utc": iso(as_of)},
        "lost_reports": lost_total,
        "found_reports": found_total,
        "active_reports": active_total,
        "claims": {"submitted": claims_submitted, "verified": transitions["VERIFIED"], "rejected": transitions["REJECTED"],
                   "cancelled": transitions["CANCELLED"]},
        "recoveries": recoveries_in_period,
        "recovery_rate_pct": _pct(recovered_n, found_total),
        "recovery_rate_non_withdrawn_pct": _pct(recovered_n, found_non_withdrawn),
        "by_category": _distribution(db, Category, Category.category_id, Category.name, Report.category_id, cohort, rec),
        "by_location": _distribution(db, Location, Location.location_id, Location.name, Report.location_id, cohort, rec),
        "monthly": _monthly(db, start, end, tz, cohort, rec),
        "average_recovery_days": _round1(float(avg_ms) / MS_PER_DAY) if recovered_n and avg_ms is not None else None,
        "median_recovery_days": _round1(float(median_ms) / MS_PER_DAY) if median_ms is not None else None,
        # Additive, non-breaking transparency fields (Blueprint 10.1: show the denominator; WITHDRAWN/CLOSED stay represented).
        "report_status_counts": {"lost": status_counts["LOST"], "found": status_counts["FOUND"]},
        "recovery_rate_basis": {"recovered_found_reports": recovered_n, "found_reports": found_total,
                                "found_reports_non_withdrawn": found_non_withdrawn},
    }


Cohort = tuple[ColumnElement[bool], ColumnElement[bool]]


def _distribution(
    db: Session, dim: type[Category] | type[Location], id_col: InstrumentedAttribute[uuid.UUID], name_col: InstrumentedAttribute[str],
    fk_col: InstrumentedAttribute[uuid.UUID], cohort: Cohort, rec: Subquery,
) -> list[dict[str, object]]:
    """LOST/FOUND counts and cohort recoveries per dimension value; sorted by display name then UUID (contract 19)."""
    rows: dict[uuid.UUID, dict[str, object]] = {}
    for dim_id, name, rtype, n in db.execute(
        select(id_col, name_col, Report.report_type, func.count()).select_from(Report).join(dim, fk_col == id_col)
        .where(*cohort).group_by(id_col, name_col, Report.report_type)
    ).all():
        row = rows.setdefault(dim_id, {"name": name, "lost": 0, "found": 0, "recoveries": 0})
        row["lost" if rtype == "LOST" else "found"] = n
    for dim_id, n in db.execute(
        select(id_col, func.count()).select_from(Report).join(dim, fk_col == id_col)
        .join(rec, rec.c.report_id == Report.report_id).where(Report.report_type == "FOUND", *cohort).group_by(id_col)
    ).all():
        rows[dim_id]["recoveries"] = n
    key = "category_id" if dim is Category else "location_id"
    ordered = sorted(rows.items(), key=lambda kv: (str(kv[1]["name"]).casefold(), str(kv[1]["name"]), str(kv[0])))
    return [{key: str(i), "name": r["name"], "lost": r["lost"], "found": r["found"], "recoveries": r["recoveries"]} for i, r in ordered]


def _monthly(db: Session, start: dt.date, end: dt.date, tz: ZoneInfo, cohort: Cohort, rec: Subquery) -> list[dict[str, object]]:
    """Report-created campus-local months; recoveries are those of FOUND reports created in the same month (contract 22)."""
    months = _months(start, end)
    bounds = [local_midnight_utc(m, tz) for m in months]
    whens: list[tuple[ColumnElement[bool], ColumnElement[int]]] = [
        (Report.created_at_utc >= b, literal_column(str(i), Integer)) for i, b in reversed(list(enumerate(bounds)))
    ]
    bucket = case(*whens, else_=literal_column("-1", Integer))
    # Bucketing in an inner query keeps GROUP BY on a plain column (SQL Server cannot match repeated bind parameters).
    inner = (
        select(bucket.label("bucket"), Report.report_type.label("rtype"),
               case((rec.c.report_id.is_not(None), 1), else_=0).label("recovered"))
        .select_from(Report).outerjoin(rec, rec.c.report_id == Report.report_id).where(*cohort).subquery()
    )
    out = [{"month": m.strftime("%Y-%m"), "lost": 0, "found": 0, "recoveries": 0} for m in months]
    for idx, rtype, n, recovered in db.execute(
        select(inner.c.bucket, inner.c.rtype, func.count(), func.sum(inner.c.recovered)).group_by(inner.c.bucket, inner.c.rtype)
    ).all():
        if idx < 0:
            continue
        out[idx]["lost" if rtype == "LOST" else "found"] = n
        if rtype == "FOUND":
            out[idx]["recoveries"] = int(recovered or 0)
    return out


# ---- activity feed ---------------------------------------------------------------------------------------
def _safe_metadata(event_type: str, raw: str | None) -> dict[str, object]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    clean = audit.sanitize_metadata(parsed) or {}
    if event_type not in REPORT_NOTE_EVENTS:
        clean.pop("decision_note", None)
    return clean


def list_activity(db: Session, page: int, page_size: int, *, event_type: str | None = None, outcome: str | None = None,
                  target_type: str | None = None) -> dict[str, object]:
    errors: dict[str, list[str]] = {}
    if event_type is not None and event_type not in audit.EVENT_TYPES:
        errors["event_type"] = ["Unknown event type."]
    if outcome is not None and outcome not in audit.OUTCOMES:
        errors["outcome"] = ["Unknown outcome."]
    if errors:
        raise unprocessable("Invalid filter.", errors)
    conds = []
    if event_type is not None:
        conds.append(ActivityLog.event_type == event_type)
    if outcome is not None:
        conds.append(ActivityLog.outcome == outcome)
    if target_type is not None:
        conds.append(ActivityLog.target_type == target_type)

    total = db.execute(select(func.count()).select_from(ActivityLog).where(*conds)).scalar_one()
    rows = db.execute(
        select(ActivityLog, User.display_name)
        .outerjoin(User, User.user_id == ActivityLog.actor_user_id)
        .where(*conds)
        .order_by(ActivityLog.created_at_utc.desc(), ActivityLog.activity_id.asc())
        .offset((page - 1) * page_size).limit(page_size)
    ).all()
    items = [
        {
            "activity_id": str(a.activity_id), "event_type": a.event_type, "target_type": a.target_type,
            "target_id": str(a.target_id) if a.target_id else None,
            "actor": {"user_id": str(a.actor_user_id), "display_name": name} if a.actor_user_id else None,
            "created_at_utc": iso(a.created_at_utc), "outcome": a.outcome, "correlation_id": a.correlation_id,
            "metadata": _safe_metadata(a.event_type, a.metadata_json),
        }
        for a, name in rows
    ]
    return {"items": items, "page": page, "page_size": page_size, "total": total}
