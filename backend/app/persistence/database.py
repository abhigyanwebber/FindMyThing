"""Engine/session setup. SQL Server via pyodbc + ODBC Driver 18 (contract §23)."""

from __future__ import annotations

import contextlib
import logging
import urllib.parse
from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

log = logging.getLogger("findmything")
DRIVER = "ODBC Driver 18 for SQL Server"


def build_sqlalchemy_url(database_url: str) -> str:
    """Accept a ready SQLAlchemy URL or a raw ODBC connection string; URL-encode ODBC params."""
    if database_url.startswith("mssql+pyodbc://"):
        return database_url
    return "mssql+pyodbc:///?odbc_connect=" + urllib.parse.quote_plus(database_url)


@lru_cache
def get_engine() -> Engine:
    url = get_settings().database_url
    if not url:
        raise RuntimeError("DATABASE_URL is not configured")
    engine = create_engine(
        build_sqlalchemy_url(url), pool_pre_ping=True, pool_size=10, max_overflow=10, future=True,
    )

    @event.listens_for(engine, "checkin")
    def _clear_session_context(dbapi_conn, _record):  # pragma: no cover - defensive pool hygiene
        # Contract §6: trigger context must never leak to the next pool user.
        try:
            cur = dbapi_conn.cursor()
            for key in ("actor_id", "reason_code", "correlation_id"):
                cur.execute(f"EXEC sp_set_session_context @key=N'{key}', @value=NULL")
            cur.close()
        except Exception:
            log.debug("could not clear session context on checkin", exc_info=True)

    return engine


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False, autoflush=False)


def reset_engine_cache() -> None:
    get_sessionmaker.cache_clear()
    get_engine.cache_clear()


@contextlib.contextmanager
def session_scope() -> Iterator[Session]:
    """One transaction per unit of work: commit on success, rollback on any exception."""
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


def set_trigger_context(session: Session, actor_id, reason_code: str, correlation_id: str) -> None:
    """Set SESSION_CONTEXT keys read by the report status-history trigger (contract §6)."""
    for key, value in (
        ("actor_id", str(actor_id) if actor_id else None),
        ("reason_code", reason_code),
        ("correlation_id", correlation_id),
    ):
        session.execute(
            text("EXEC sp_set_session_context @key=:k, @value=:v"), {"k": key, "v": value}
        )


def clear_trigger_context(session: Session) -> None:
    for key in ("actor_id", "reason_code", "correlation_id"):
        session.execute(text("EXEC sp_set_session_context @key=:k, @value=NULL"), {"k": key})
