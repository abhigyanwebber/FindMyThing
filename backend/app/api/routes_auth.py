"""Auth + health routes."""

from __future__ import annotations

import logging

from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import RequestInfo, check_origin, get_db, request_info, require_auth
from app.core.config import REPO_ROOT, get_settings
from app.persistence.database import get_engine
from app.schemas.base import Strict
from app.services import auth as auth_service
from app.services.auth import AuthContext


class RegisterBody(Strict):
    display_name: str
    email: str
    password: str


class LoginBody(Strict):
    email: str
    password: str


router = APIRouter()
log = logging.getLogger("findmything")


def _user_dto(user, role: str) -> dict:
    return {"user_id": str(user.user_id), "display_name": user.display_name, "email": user.email_normalized, "role": role}


def _set_cookie(response: Response, token: str) -> None:
    s = get_settings()
    response.set_cookie(
        s.session_cookie_name, token, max_age=s.session_max_age_seconds, path="/", httponly=True,
        secure=s.cookie_secure, samesite="lax",
    )


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


def _head_revision() -> str:
    cfg = AlembicConfig(str(REPO_ROOT / "backend" / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "backend" / "migrations"))
    return ScriptDirectory.from_config(cfg).get_current_head()


@router.get("/health/ready")
def ready(response: Response) -> dict:
    """SQL reachable and Alembic revision == head. Reveals no detail (contract §4.1)."""
    try:
        with get_engine().connect() as conn:
            current = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        if current == _head_revision():
            return {"status": "ready"}
    except Exception:
        log.warning("readiness check failed", exc_info=True)
    response.status_code = 503
    return {"status": "not_ready"}


@router.post("/auth/register", status_code=201)
def register(body: RegisterBody, request: Request, response: Response, db: Session = Depends(get_db),
             info: RequestInfo = Depends(request_info)) -> dict:
    check_origin(request)
    issued = auth_service.register(
        db, display_name=body.display_name, email=body.email, password=body.password, ip=info.ip,
        correlation_id=info.request_id, user_agent=info.user_agent,
        existing_token=request.cookies.get(get_settings().session_cookie_name),
    )
    _set_cookie(response, issued.session_token)
    return {"user": _user_dto(issued.user, issued.role), "csrf_token": issued.csrf_token}


@router.post("/auth/login")
def login(body: LoginBody, request: Request, response: Response, db: Session = Depends(get_db),
          info: RequestInfo = Depends(request_info)) -> dict:
    check_origin(request)
    issued = auth_service.login(
        db, email=body.email, password=body.password, ip=info.ip, correlation_id=info.request_id,
        user_agent=info.user_agent, existing_token=request.cookies.get(get_settings().session_cookie_name),
    )
    _set_cookie(response, issued.session_token)
    return {"user": _user_dto(issued.user, issued.role), "csrf_token": issued.csrf_token}


@router.post("/auth/logout", status_code=204)
def logout(response: Response, ctx: AuthContext = Depends(require_auth), db: Session = Depends(get_db),
           info: RequestInfo = Depends(request_info)) -> Response:
    auth_service.logout(db, ctx, info.request_id)
    out = Response(status_code=204)
    s = get_settings()
    out.delete_cookie(s.session_cookie_name, path="/", httponly=True, secure=s.cookie_secure, samesite="lax")
    return out


@router.get("/auth/me")
def me(ctx: AuthContext = Depends(require_auth)) -> dict:
    return {"user": _user_dto(ctx.user, ctx.role)}


@router.get("/auth/csrf")
def csrf(ctx: AuthContext = Depends(require_auth), db: Session = Depends(get_db)) -> dict:
    return {"csrf_token": auth_service.rotate_csrf(db, ctx)}

