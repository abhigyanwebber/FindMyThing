"""FastAPI application factory (Blueprint §2, contract §1/§21)."""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.deps import resolve_request_id
from app.core.config import get_settings
from app.core.errors import AppError

log = logging.getLogger("findmything")


def _envelope(request: Request, status: int, code: str, message: str, field_errors=None, headers=None) -> JSONResponse:
    body: dict = {"error": {"code": code, "message": message, "request_id": getattr(request.state, "request_id", "")}}
    if field_errors:
        body["error"]["field_errors"] = field_errors
    return JSONResponse(status_code=status, content=body, headers=headers)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    poller = None
    if settings.matching_worker_enabled and settings.database_url:
        from app.services.matching_worker import MatchingPoller

        poller = MatchingPoller(settings.matching_poll_seconds)
        poller.start()
    try:
        yield
    finally:
        if poller:
            poller.stop()


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
    app = FastAPI(title="FindMyThing API", lifespan=lifespan, docs_url=None if settings.is_production else "/api/docs",
                  redoc_url=None, openapi_url=None if settings.is_production else "/api/openapi.json")

    app.add_middleware(
        CORSMiddleware, allow_origins=[settings.frontend_origin], allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-CSRF-Token", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Retry-After"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.request_id = resolve_request_id(request.headers.get("x-request-id"))
        try:
            response = await call_next(request)
        except Exception:  # last-resort guard; handlers below normally catch first
            log.exception("unhandled error request_id=%s", request.state.request_id)
            response = _envelope(request, 500, "INTERNAL_ERROR", "An unexpected error occurred.")
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError):
        return _envelope(request, exc.status_code, exc.code, exc.message, exc.field_errors, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        errors = exc.errors()
        if any(e.get("type") in ("json_invalid", "model_attributes_type") for e in errors):
            return _envelope(request, 400, "BAD_REQUEST", "Malformed request body.")
        fields: dict[str, list[str]] = {}
        for e in errors:
            loc = [str(p) for p in e.get("loc", []) if p not in ("body", "query", "path")]
            key = ".".join(loc) or "request"
            msg = "Unknown field." if e.get("type") == "extra_forbidden" else (e.get("msg") or "Invalid value.")
            fields.setdefault(key, []).append(msg)
        return _envelope(request, 422, "VALIDATION_ERROR", "Request validation failed.", fields)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        codes = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED", 401: "UNAUTHENTICATED", 403: "FORBIDDEN"}
        return _envelope(request, exc.status_code, codes.get(exc.status_code, "ERROR"),
                         "Resource not found." if exc.status_code == 404 else "Request could not be completed.")

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        log.exception("unhandled error request_id=%s", getattr(request.state, "request_id", ""))
        return _envelope(request, 500, "INTERNAL_ERROR", "An unexpected error occurred.")

    from app.api import routes_auth, routes_claims, routes_matches, routes_reports

    app.include_router(routes_auth.router, prefix="/api")
    app.include_router(routes_reports.router, prefix="/api")
    app.include_router(routes_matches.router, prefix="/api")
    app.include_router(routes_claims.router, prefix="/api")
    return app


app = create_app()
_ = uuid
