"""Claim and moderation routes (contract §4.4)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from pydantic import Field
from sqlalchemy.orm import Session

from app.api.deps import RequestInfo, get_db, request_info, require_auth, require_moderator
from app.api.routes_reports import paging, reject_unknown_query
from app.schemas.base import Strict
from app.services import claims as svc
from app.services.auth import AuthContext

router = APIRouter()


class SubmitClaimBody(Strict):
    claim_statement: str
    lost_report_id: uuid.UUID | None = None


class VersionBody(Strict):
    expected_version: int = Field(ge=1)


class DecisionBody(Strict):
    decision_note: str | None = None
    expected_version: int = Field(ge=1)


class RejectBody(Strict):
    reason_code: str
    decision_note: str | None = None
    expected_version: int = Field(ge=1)


class InfoBody(Strict):
    decision_note: str
    expected_version: int = Field(ge=1)


class VoidBody(Strict):
    decision_note: str
    expected_claim_version: int = Field(ge=1)


@router.post("/reports/{found_report_id}/claims", status_code=201)
def submit(found_report_id: uuid.UUID, body: SubmitClaimBody, ctx: AuthContext = Depends(require_auth),
           db: Session = Depends(get_db), info: RequestInfo = Depends(request_info)) -> dict:
    return {"claim": svc.submit_claim(db, ctx, found_report_id, claim_statement=body.claim_statement,
                                      lost_report_id=body.lost_report_id, corr=info.request_id)}


@router.get("/me/claims")
def my_claims(request: Request, ctx: AuthContext = Depends(require_auth), db: Session = Depends(get_db),
              pg: tuple[int, int] = Depends(paging)) -> dict:
    reject_unknown_query(request, {"page", "page_size"})
    return svc.list_my_claims(db, ctx, pg[0], pg[1])


@router.get("/claims/{claim_id}")
def get_claim(claim_id: uuid.UUID, ctx: AuthContext = Depends(require_auth), db: Session = Depends(get_db)) -> dict:
    return {"claim": svc.get_own_claim(db, ctx, claim_id)}


@router.post("/claims/{claim_id}/cancel")
def cancel(claim_id: uuid.UUID, body: VersionBody, ctx: AuthContext = Depends(require_auth), db: Session = Depends(get_db),
           info: RequestInfo = Depends(request_info)) -> dict:
    return {"claim": svc.cancel_claim(db, ctx, claim_id, body.expected_version, info.request_id)}


@router.get("/moderation/claims")
def mod_list(request: Request, status: str | None = None, ctx: AuthContext = Depends(require_moderator),
             db: Session = Depends(get_db), pg: tuple[int, int] = Depends(paging)) -> dict:
    reject_unknown_query(request, {"status", "page", "page_size"})
    return svc.moderator_list(db, status, pg[0], pg[1])


@router.get("/moderation/claims/{claim_id}")
def mod_detail(claim_id: uuid.UUID, ctx: AuthContext = Depends(require_moderator), db: Session = Depends(get_db),
               info: RequestInfo = Depends(request_info)) -> dict:
    return {"claim": svc.moderator_detail(db, ctx, claim_id, info.request_id)}


@router.post("/moderation/claims/{claim_id}/verify")
def verify(claim_id: uuid.UUID, body: DecisionBody, ctx: AuthContext = Depends(require_moderator), db: Session = Depends(get_db),
           info: RequestInfo = Depends(request_info)) -> dict:
    return {"claim": svc.verify_claim(db, ctx, claim_id, body.decision_note, body.expected_version, info.request_id)}


@router.post("/moderation/claims/{claim_id}/reject")
def reject(claim_id: uuid.UUID, body: RejectBody, ctx: AuthContext = Depends(require_moderator), db: Session = Depends(get_db),
           info: RequestInfo = Depends(request_info)) -> dict:
    return {"claim": svc.reject_claim(db, ctx, claim_id, body.reason_code, body.decision_note, body.expected_version, info.request_id)}


@router.post("/moderation/claims/{claim_id}/revoke-verification")
def revoke(claim_id: uuid.UUID, body: DecisionBody, ctx: AuthContext = Depends(require_moderator), db: Session = Depends(get_db),
           info: RequestInfo = Depends(request_info)) -> dict:
    return {"claim": svc.revoke_verification(db, ctx, claim_id, body.decision_note, body.expected_version, info.request_id)}


@router.post("/moderation/claims/{claim_id}/request-information")
def request_info_route(claim_id: uuid.UUID, body: InfoBody, ctx: AuthContext = Depends(require_moderator),
                       db: Session = Depends(get_db), info: RequestInfo = Depends(request_info)) -> dict:
    return {"claim": svc.request_information(db, ctx, claim_id, body.decision_note, body.expected_version, info.request_id)}


@router.post("/moderation/claims/{claim_id}/recover")
def recover(claim_id: uuid.UUID, body: DecisionBody, ctx: AuthContext = Depends(require_moderator), db: Session = Depends(get_db),
            info: RequestInfo = Depends(request_info)) -> dict:
    return svc.complete_recovery(db, ctx, claim_id, body.decision_note, body.expected_version, info.request_id)


@router.post("/moderation/recoveries/{recovery_id}/void")
def void(recovery_id: uuid.UUID, body: VoidBody, ctx: AuthContext = Depends(require_moderator), db: Session = Depends(get_db),
         info: RequestInfo = Depends(request_info)) -> dict:
    return svc.void_recovery(db, ctx, recovery_id, body.decision_note, body.expected_claim_version, info.request_id)
