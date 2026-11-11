"""Report routes (contract §4.2)."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from pydantic import Field
from sqlalchemy.orm import Session

from app.api.deps import RequestInfo, get_db, request_info, require_auth, require_moderator
from app.core.errors import unprocessable
from app.schemas.base import Strict
from app.services import reports as svc
from app.services.auth import AuthContext

router = APIRouter()

ALLOWED_LIST_PARAMS = {"type", "status", "category_id", "location_id", "q", "page", "page_size"}


def reject_unknown_query(request: Request, allowed: set[str]) -> None:
    unknown = sorted(set(request.query_params.keys()) - allowed)
    if unknown:
        raise unprocessable("Unknown query parameters.", {k: ["Unknown filter."] for k in unknown})


def paging(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)) -> tuple[int, int]:
    return page, page_size


class CreateReportBody(Strict):
    report_type: str
    category_id: uuid.UUID
    location_id: uuid.UUID
    title: str
    description: str
    occurred_on: dt.date


class PatchReportBody(Strict):
    title: str | None = None
    description: str | None = None
    occurred_on: dt.date | None = None
    expected_version: int = Field(ge=1)


class VersionBody(Strict):
    expected_version: int = Field(ge=1)


class CloseBody(Strict):
    reason_code: str
    decision_note: str | None = None
    expected_version: int = Field(ge=1)


class ReopenBody(Strict):
    decision_note: str | None = None
    expected_version: int = Field(ge=1)


class CorrectBody(Strict):
    title: str | None = None
    description: str | None = None
    occurred_on: dt.date | None = None
    category_id: uuid.UUID | None = None
    location_id: uuid.UUID | None = None
    decision_note: str | None = None
    expected_version: int = Field(ge=1)


@router.get("/reports")
def list_reports(
    request: Request, ctx: AuthContext = Depends(require_auth), db: Session = Depends(get_db),
    type: Annotated[str | None, Query()] = None, status: Annotated[str | None, Query()] = None,
    category_id: uuid.UUID | None = None, location_id: uuid.UUID | None = None, q: str | None = None,
    pg: tuple[int, int] = Depends(paging),
) -> dict:
    reject_unknown_query(request, ALLOWED_LIST_PARAMS)
    return svc.list_reports(db, ctx, report_type=type, status=status, category_id=category_id, location_id=location_id,
                            q=q, page=pg[0], page_size=pg[1])


@router.post("/reports", status_code=201)
def create_report(body: CreateReportBody, ctx: AuthContext = Depends(require_auth), db: Session = Depends(get_db),
                  info: RequestInfo = Depends(request_info)) -> dict:
    return svc.create_report(db, ctx, report_type=body.report_type, category_id=body.category_id,
                             location_id=body.location_id, title=body.title, description=body.description,
                             occurred_on=body.occurred_on, correlation_id=info.request_id)


@router.get("/reports/{report_id}")
def get_report(report_id: uuid.UUID, ctx: AuthContext = Depends(require_auth), db: Session = Depends(get_db)) -> dict:
    return svc.report_detail(db, ctx, report_id)


@router.patch("/reports/{report_id}")
def patch_report(report_id: uuid.UUID, body: PatchReportBody, ctx: AuthContext = Depends(require_auth),
                 db: Session = Depends(get_db), info: RequestInfo = Depends(request_info)) -> dict:
    return svc.update_report(db, ctx, report_id, title=body.title, description=body.description,
                             occurred_on=body.occurred_on, expected_version=body.expected_version,
                             correlation_id=info.request_id)


@router.post("/reports/{report_id}/withdraw")
def withdraw(report_id: uuid.UUID, body: VersionBody, ctx: AuthContext = Depends(require_auth),
             db: Session = Depends(get_db), info: RequestInfo = Depends(request_info)) -> dict:
    return svc.withdraw_report(db, ctx, report_id, expected_version=body.expected_version, correlation_id=info.request_id)


@router.post("/moderation/reports/{report_id}/close")
def close(report_id: uuid.UUID, body: CloseBody, ctx: AuthContext = Depends(require_moderator),
          db: Session = Depends(get_db), info: RequestInfo = Depends(request_info)) -> dict:
    return svc.close_report(db, ctx, report_id, reason_code=body.reason_code, decision_note=body.decision_note,
                            expected_version=body.expected_version, correlation_id=info.request_id)


@router.post("/moderation/reports/{report_id}/reopen")
def reopen(report_id: uuid.UUID, body: ReopenBody, ctx: AuthContext = Depends(require_moderator),
           db: Session = Depends(get_db), info: RequestInfo = Depends(request_info)) -> dict:
    return svc.reopen_report(db, ctx, report_id, decision_note=body.decision_note,
                             expected_version=body.expected_version, correlation_id=info.request_id)


@router.post("/moderation/reports/{report_id}/correct")
def correct(report_id: uuid.UUID, body: CorrectBody, ctx: AuthContext = Depends(require_moderator),
            db: Session = Depends(get_db), info: RequestInfo = Depends(request_info)) -> dict:
    return svc.moderator_correct(db, ctx, report_id, title=body.title, description=body.description,
                                 occurred_on=body.occurred_on, category_id=body.category_id,
                                 location_id=body.location_id, decision_note=body.decision_note,
                                 expected_version=body.expected_version, correlation_id=info.request_id)


@router.get("/reference-data")
def reference_data(ctx: AuthContext = Depends(require_auth), db: Session = Depends(get_db)) -> dict:
    """Read-only taxonomy for forms/filters (assumption A-005: contract lists no such route)."""
    from sqlalchemy import select

    from app.core.config import get_campus_config
    from app.persistence.models import Category, Location

    # T-SQL has no `IS 1`: compare with == True (compiles to = 1).
    cats = db.scalars(select(Category).where(Category.is_active == True).order_by(Category.name, Category.category_id)).all()
    locs = db.scalars(select(Location).where(Location.is_active == True).order_by(Location.name, Location.location_id)).all()
    names = {x.location_id: x.name for x in locs}
    return {
        "campus": {"display_name": get_campus_config()["campus_display_name"], "timezone": get_campus_config()["timezone"]},
        "categories": [{"category_id": str(c.category_id), "name": c.name} for c in cats],
        "locations": [
            {"location_id": str(x.location_id), "name": x.name, "is_zone": x.is_zone,
             "zone_name": names.get(x.zone_id) if x.zone_id else x.name}
            for x in locs
        ],
    }