"""Row-lock helpers (contract §24). Lock order is global and deterministic:
reports (ascending id) -> claims (ascending id) -> recoveries (ascending id).

Ordering uses the canonical lowercase UUID string. Only *consistency* across workflows matters for
deadlock avoidance (SQL Server's own uniqueidentifier collation order is irrelevant), and each row
is locked with its own statement so the acquisition order is exactly this order.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.persistence.models import Claim, Recovery, Report

HINT = "WITH (UPDLOCK, HOLDLOCK)"


def _ordered(ids: Iterable[uuid.UUID | None]) -> list[uuid.UUID]:
    return sorted({i for i in ids if i is not None}, key=lambda u: str(u))


def lock_reports(db: Session, ids: Iterable[uuid.UUID | None]) -> dict[uuid.UUID, Report]:
    out: dict[uuid.UUID, Report] = {}
    for rid in _ordered(ids):
        row = db.execute(
            select(Report).where(Report.report_id == rid).with_hint(Report, HINT, "mssql")
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if row is not None:
            out[rid] = row
    return out


def lock_claims(db: Session, ids: Iterable[uuid.UUID | None]) -> dict[uuid.UUID, Claim]:
    out: dict[uuid.UUID, Claim] = {}
    for cid in _ordered(ids):
        row = db.execute(
            select(Claim).where(Claim.claim_id == cid).with_hint(Claim, HINT, "mssql")
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if row is not None:
            out[cid] = row
    return out


def lock_recoveries(db: Session, ids: Iterable[uuid.UUID | None]) -> dict[uuid.UUID, Recovery]:
    out: dict[uuid.UUID, Recovery] = {}
    for rid in _ordered(ids):
        row = db.execute(
            select(Recovery).where(Recovery.recovery_id == rid).with_hint(Recovery, HINT, "mssql")
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if row is not None:
            out[rid] = row
    return out
