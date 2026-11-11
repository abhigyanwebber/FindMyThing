"""Registration, login, sessions, CSRF (contract §4.1, §9)."""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import ratelimit
from app.core.config import get_settings
from app.core.errors import AppError, conflict, unauthenticated
from app.core.security import (
    constant_time_equal,
    digest,
    hash_password,
    needs_rehash,
    new_id,
    new_token,
    utcnow,
    verify_password,
)
from app.core.text import clean_text, normalize_email, validate_password
from app.persistence.models import Role, SessionRow, User
from app.services import audit
from app.services.seed import moderator_role_id, student_role_id

LOGIN_EMAIL_LIMIT, LOGIN_IP_LIMIT, LOGIN_WINDOW = 5, 20, 15 * 60
REGISTER_IP_LIMIT, REGISTER_WINDOW = 5, 60 * 60


@dataclass
class AuthContext:
    user: User
    role: str
    session: SessionRow

    @property
    def is_moderator(self) -> bool:
        return self.role == "MODERATOR"


@dataclass
class IssuedSession:
    user: User
    role: str
    session_token: str
    csrf_token: str


def role_name_for(db: Session, user: User) -> str:
    if user.role_id == moderator_role_id():
        return "MODERATOR"
    if user.role_id == student_role_id():
        return "STUDENT"
    return db.scalar(select(Role.name).where(Role.role_id == user.role_id)) or "STUDENT"


def _issue(db: Session, user: User, user_agent: str | None) -> IssuedSession:
    settings = get_settings()
    now = utcnow()
    token, csrf = new_token(), new_token()
    db.add(
        SessionRow(
            session_token_hash=digest(token), user_id=user.user_id, csrf_token_hash=digest(csrf),
            created_at_utc=now, expires_at_utc=now + dt.timedelta(seconds=settings.session_max_age_seconds),
            last_seen_at_utc=now, user_agent_summary=(user_agent or "")[:256] or None,
        )
    )
    db.flush()
    return IssuedSession(user=user, role=role_name_for(db, user), session_token=token, csrf_token=csrf)


def revoke_session_by_token(db: Session, raw_token: str | None) -> None:
    if not raw_token:
        return
    db.execute(
        update(SessionRow)
        .where(SessionRow.session_token_hash == digest(raw_token), SessionRow.revoked_at_utc.is_(None))
        .values(revoked_at_utc=utcnow())
    )


def revoke_all_sessions(db: Session, user_id: uuid.UUID) -> None:
    db.execute(
        update(SessionRow).where(SessionRow.user_id == user_id, SessionRow.revoked_at_utc.is_(None)).values(revoked_at_utc=utcnow())
    )


def register(db: Session, *, display_name: str, email: str, password: str, ip: str, correlation_id: str,
             user_agent: str | None, existing_token: str | None) -> IssuedSession:
    count, retry = ratelimit.increment(db, "register_ip", ip, REGISTER_WINDOW)
    if count > REGISTER_IP_LIMIT:
        audit.log_event(db, event_type="RATE_LIMIT_TRIGGERED", outcome="DENIED", correlation_id=correlation_id,
                        metadata={"limit_name": "register_ip"})
        db.commit()
        raise ratelimit.throttled(retry)

    name = clean_text(display_name, field="display_name", min_len=1, max_len=80)
    normalized = normalize_email(email)
    validate_password(password)

    user = User(
        user_id=new_id(), role_id=student_role_id(), display_name=name, email_normalized=normalized,
        password_hash=hash_password(password), is_active=True, created_at_utc=utcnow(), updated_at_utc=utcnow(),
    )
    try:
        with db.begin_nested():
            db.add(user)
            db.flush()
    except IntegrityError:
        db.commit()  # persist the rate-limit increment
        raise conflict("EMAIL_UNAVAILABLE", "An account with these details cannot be created.") from None
    revoke_session_by_token(db, existing_token)
    issued = _issue(db, user, user_agent)
    audit.log_event(db, event_type="AUTH_REGISTERED", outcome="SUCCESS", correlation_id=correlation_id,
                    actor_user_id=user.user_id, target_type="USER", target_id=user.user_id)
    return issued


def login(db: Session, *, email: str, password: str, ip: str, correlation_id: str, user_agent: str | None,
          existing_token: str | None) -> IssuedSession:
    try:
        normalized = normalize_email(email)
    except AppError:
        normalized = "invalid"
    e_count, e_retry = ratelimit.current_count(db, "login_email", normalized, LOGIN_WINDOW)
    i_count, i_retry = ratelimit.current_count(db, "login_ip", ip, LOGIN_WINDOW)
    if e_count >= LOGIN_EMAIL_LIMIT or i_count >= LOGIN_IP_LIMIT:
        audit.log_event(db, event_type="RATE_LIMIT_TRIGGERED", outcome="DENIED", correlation_id=correlation_id,
                        metadata={"limit_name": "login_email" if e_count >= LOGIN_EMAIL_LIMIT else "login_ip"})
        db.commit()
        waits = [w for hit, w in ((e_count >= LOGIN_EMAIL_LIMIT, e_retry), (i_count >= LOGIN_IP_LIMIT, i_retry)) if hit]
        raise ratelimit.throttled(max(waits))

    user = db.scalar(select(User).where(User.email_normalized == normalized))
    ok = verify_password(user.password_hash if user else None, password) and user is not None and user.is_active
    if not ok:
        ratelimit.increment(db, "login_email", normalized, LOGIN_WINDOW)
        ratelimit.increment(db, "login_ip", ip, LOGIN_WINDOW)
        audit.log_event(db, event_type="AUTH_LOGIN_FAILED", outcome="FAILURE", correlation_id=correlation_id)
        db.commit()
        raise unauthenticated("Invalid email or password.")

    assert user is not None
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    revoke_session_by_token(db, existing_token)
    issued = _issue(db, user, user_agent)
    audit.log_event(db, event_type="AUTH_LOGIN_SUCCEEDED", outcome="SUCCESS", correlation_id=correlation_id,
                    actor_user_id=user.user_id, target_type="USER", target_id=user.user_id)
    return issued


def logout(db: Session, ctx: AuthContext, correlation_id: str) -> None:
    ctx.session.revoked_at_utc = utcnow()
    audit.log_event(db, event_type="AUTH_LOGOUT", outcome="SUCCESS", correlation_id=correlation_id,
                    actor_user_id=ctx.user.user_id, target_type="USER", target_id=ctx.user.user_id)


def load_context(db: Session, raw_token: str | None) -> AuthContext | None:
    if not raw_token:
        return None
    settings = get_settings()
    row = db.get(SessionRow, digest(raw_token))
    now = utcnow()
    if row is None or row.revoked_at_utc is not None or row.expires_at_utc <= now:
        return None
    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        return None
    if (now - row.last_seen_at_utc).total_seconds() >= settings.last_seen_throttle_seconds:
        row.last_seen_at_utc = now
    return AuthContext(user=user, role=role_name_for(db, user), session=row)


def rotate_csrf(db: Session, ctx: AuthContext) -> str:
    """Return a raw CSRF token for the session. Raw tokens are never stored, so a fresh one replaces the hash."""
    token = new_token()
    ctx.session.csrf_token_hash = digest(token)
    db.flush()
    return token


def csrf_matches(ctx: AuthContext, presented: str | None) -> bool:
    if not presented:
        return False
    return constant_time_equal(digest(presented), bytes(ctx.session.csrf_token_hash))
