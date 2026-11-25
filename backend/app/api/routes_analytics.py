"""Moderator analytics and activity routes (contract 4.5). Moderator only; read-only."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_moderator
from app.api.routes_reports import paging, reject_unknown_query
from app.services import analytics as svc
from app.services.auth import AuthContext

router = APIRouter()


@router.get("/moderation/analytics/summary")
def analytics_summary(
    request: Request, date_from: dt.date | None = Query(None, alias="from"), date_to: dt.date | None = Query(None, alias="to"),
    ctx: AuthContext = Depends(require_moderator), db: Session = Depends(get_db),
) -> dict[str, object]:
    reject_unknown_query(request, {"from", "to"})
    return svc.analytics_summary(db, date_from, date_to)


@router.get("/moderation/activity")
def activity_feed(
    request: Request, event_type: str | None = Query(None, max_length=64), outcome: str | None = Query(None, max_length=16),
    target_type: str | None = Query(None, max_length=32), pg: tuple[int, int] = Depends(paging),
    ctx: AuthContext = Depends(require_moderator), db: Session = Depends(get_db),
) -> dict[str, object]:
    reject_unknown_query(request, {"page", "page_size", "event_type", "outcome", "target_type"})
    return svc.list_activity(db, pg[0], pg[1], event_type=event_type, outcome=outcome, target_type=target_type)
