"""Matching routes (contract 4.3)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.api.deps import RequestInfo, get_db, request_info, require_auth, require_moderator
from app.api.routes_reports import paging, reject_unknown_query
from app.schemas.base import Strict
from app.services import matches as svc
from app.services.auth import AuthContext

router = APIRouter()


class EmptyBody(Strict):
    pass


class DismissBody(Strict):
    reason_code: str
    decision_note: str | None = None


@router.get("/reports/{report_id}/matches")
def list_matches(report_id: uuid.UUID, request: Request, ctx: AuthContext = Depends(require_auth),
                 db: Session = Depends(get_db), pg: tuple[int, int] = Depends(paging)) -> dict:
    reject_unknown_query(request, {"page", "page_size"})
    return svc.list_matches(db, ctx, report_id, pg[0], pg[1])


@router.post("/reports/{report_id}/matches/recalculate")
def recalculate(report_id: uuid.UUID, body: EmptyBody, response: Response, ctx: AuthContext = Depends(require_auth),
                db: Session = Depends(get_db), info: RequestInfo = Depends(request_info)) -> dict:
    status, payload = svc.recalculate(db, ctx, report_id, info.request_id)
    response.status_code = status
    return payload


@router.post("/moderation/matches/{match_id}/dismiss")
def dismiss(match_id: uuid.UUID, body: DismissBody, ctx: AuthContext = Depends(require_moderator),
            db: Session = Depends(get_db), info: RequestInfo = Depends(request_info)) -> dict:
    return svc.dismiss(db, ctx, match_id, body.reason_code, body.decision_note, info.request_id)
