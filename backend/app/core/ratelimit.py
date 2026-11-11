"""SQL-backed fixed-window rate limiting (contract §9, §15). No Redis; raw keys are never stored."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.security import key_hash, new_id, utcnow


def _window(now: dt.datetime, seconds: int) -> tuple[dt.datetime, int]:
    epoch = int(now.timestamp())
    start = epoch - (epoch % seconds)
    start_dt = dt.datetime.fromtimestamp(start, tz=dt.timezone.utc)
    retry_after = max(1, int((start_dt + dt.timedelta(seconds=seconds) - now).total_seconds()))
    return start_dt, retry_after


def current_count(db: Session, name: str, key: str, window_seconds: int) -> tuple[int, int]:
    """Return (count in current window, seconds until the window resets)."""
    now = utcnow()
    start, retry = _window(now, window_seconds)
    row = db.execute(
        text("SELECT count FROM rate_limit_counters WHERE key_hash=:k AND window_start_utc=:w AND window_seconds=:s"),
        {"k": key_hash(name, key), "w": start.replace(tzinfo=None), "s": window_seconds},
    ).first()
    return (row[0] if row else 0), retry


def increment(db: Session, name: str, key: str, window_seconds: int) -> tuple[int, int]:
    """Atomically increment the counter for the current window; returns (new count, retry_after)."""
    now = utcnow()
    start, retry = _window(now, window_seconds)
    params = {"k": key_hash(name, key), "w": start.replace(tzinfo=None), "s": window_seconds}
    upd = text(
        "UPDATE rate_limit_counters WITH (UPDLOCK, HOLDLOCK) SET count = count + 1 "
        "OUTPUT inserted.count WHERE key_hash=:k AND window_start_utc=:w AND window_seconds=:s"
    )
    for _ in range(3):
        row = db.execute(upd, params).first()
        if row is not None:
            return row[0], retry
        try:
            with db.begin_nested():
                db.execute(
                    text(
                        "INSERT INTO rate_limit_counters (counter_id,key_hash,window_start_utc,window_seconds,count,expires_at_utc) "
                        "VALUES (:id,:k,:w,:s,1,:e)"
                    ),
                    {**params, "id": new_id(), "e": (start + dt.timedelta(seconds=window_seconds * 2)).replace(tzinfo=None)},
                )
            return 1, retry
        except IntegrityError:
            continue  # lost an insert race; the next UPDATE will find the row
    raise AppError(503, "DEPENDENCY_UNAVAILABLE", "A required service is temporarily unavailable.")


def throttled(retry_after: int, message: str = "Too many attempts. Try again later.") -> AppError:
    return AppError(429, "RATE_LIMITED", message, headers={"Retry-After": str(retry_after)})


def purge_expired(db: Session) -> int:
    res = db.execute(text("DELETE FROM rate_limit_counters WHERE expires_at_utc < :n"), {"n": utcnow().replace(tzinfo=None)})
    return res.rowcount or 0
