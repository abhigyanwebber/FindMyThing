"""Row factories for tests (ORM-level, bypass services on purpose)."""

from __future__ import annotations

import datetime as dt
import json
import uuid

from sqlalchemy.orm import Session

from app.core.security import hash_password, new_id, seed_id, utcnow
from app.persistence.models import Claim, Report, User

_PW_HASH = None


def pw_hash() -> str:
    global _PW_HASH
    if _PW_HASH is None:
        _PW_HASH = hash_password("correct horse battery staple")
    return _PW_HASH


def make_user(db: Session, role: str = "STUDENT", name: str = "Test User", email: str | None = None) -> User:
    now = utcnow()
    u = User(
        user_id=new_id(), role_id=seed_id("role", role), display_name=name,
        email_normalized=email or f"{uuid.uuid4().hex[:10]}@example.com", password_hash=pw_hash(),
        is_active=True, created_at_utc=now, updated_at_utc=now,
    )
    db.add(u)
    db.flush()
    return u


def cat(slug: str = "electronics") -> uuid.UUID:
    return seed_id("category", slug)


def loc(slug: str = "library") -> uuid.UUID:
    return seed_id("location", slug)


def make_report(
    db: Session, owner: User, rtype: str = "FOUND", *, category: str = "electronics", location: str = "library",
    title: str = "Black laptop bag", description: str = "Black laptop bag with a charger inside",
    occurred_on: dt.date | None = None, status: str = "ACTIVE",
) -> Report:
    now = utcnow()
    r = Report(
        report_id=new_id(), reporter_user_id=owner.user_id, report_type=rtype, category_id=cat(category),
        location_id=loc(location), title=title, description=description,
        occurred_on=occurred_on or dt.date.today(), status=status, status_changed_at_utc=now,
        created_at_utc=now, updated_at_utc=now, version=1, matching_version=1,
    )
    db.add(r)
    db.flush()
    return r


def make_claim(db: Session, claimant: User, found: Report, lost: Report | None = None, status: str = "PENDING") -> Claim:
    now = utcnow()
    c = Claim(
        claim_id=new_id(), found_report_id=found.report_id, claimant_user_id=claimant.user_id,
        lost_report_id=lost.report_id if lost else None, claim_statement="It has my initials sewn inside.",
        status=status, version=1, found_report_version_at_submission=found.version,
        lost_report_version_at_submission=lost.version if lost else None,
        report_snapshot=json.dumps({"found": {"title": found.title}}), created_at_utc=now,
        updated_at_utc=now, status_changed_at_utc=now,
    )
    db.add(c)
    db.flush()
    return c
