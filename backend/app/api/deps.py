"""FastAPI dependencies: DB session per request, request context, authentication, CSRF/Origin."""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator
from dataclasses import dataclass

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import forbidden, unauthenticated
from app.persistence.database import clear_trigger_context, get_sessionmaker
from app.services.auth import AuthContext, csrf_matches, load_context

_REQUEST_ID_RE = re.compile(r"^[\x21-\x7e]{1,128}$")
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def resolve_request_id(header_value: str | None) -> str:
    if header_value and _REQUEST_ID_RE.match(header_value):
        return header_value
    return str(uuid.uuid4())


def client_ip(request: Request) -> str:
    """Trusted source IP. X-Forwarded-For is honoured only when explicitly enabled (App Service)."""
    settings = get_settings()
    if settings.trust_forwarded_for:
        xff = request.headers.get("x-forwarded-for", "")
        if xff:
            # The platform front end appends the real client address last; earlier entries are client-supplied.
            last = xff.split(",")[-1].strip()
            if last.count(":") == 1:  # IPv4:port
                last = last.split(":")[0]
            if last:
                return last
    return request.client.host if request.client else "unknown"


def get_db() -> Iterator[Session]:
    """One transaction per request: commit on success, roll back on any exception (contract §24)."""
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        try:
            clear_trigger_context(session)
            session.commit()
        except Exception:
            session.rollback()
        session.close()


@dataclass
class RequestInfo:
    request_id: str
    ip: str
    user_agent: str | None


def request_info(request: Request) -> RequestInfo:
    return RequestInfo(
        request_id=getattr(request.state, "request_id", None) or str(uuid.uuid4()),
        ip=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )


def check_origin(request: Request) -> None:
    """Exact configured Origin is required on cookie-authenticated unsafe requests (contract §4.1)."""
    origin = request.headers.get("origin")
    if origin is None or origin != get_settings().frontend_origin:
        raise forbidden("Request origin is not allowed.", code="ORIGIN_NOT_ALLOWED")


def optional_auth(request: Request, db: Session = Depends(get_db)) -> AuthContext | None:
    return load_context(db, request.cookies.get(get_settings().session_cookie_name))


def require_auth(request: Request, ctx: AuthContext | None = Depends(optional_auth)) -> AuthContext:
    if ctx is None:
        raise unauthenticated()
    if request.method in UNSAFE_METHODS:
        check_origin(request)
        if not csrf_matches(ctx, request.headers.get("x-csrf-token")):
            raise forbidden("Missing or invalid CSRF token.", code="CSRF_INVALID")
    return ctx


def require_student(ctx: AuthContext = Depends(require_auth)) -> AuthContext:
    if ctx.role != "STUDENT":
        raise forbidden()
    return ctx


def require_moderator(ctx: AuthContext = Depends(require_auth)) -> AuthContext:
    if ctx.role != "MODERATOR":
        raise forbidden()
    return ctx
