"""Idempotent reference-data seed (contract §7, §16). Never creates users; never renames used rows."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import seed_id
from app.persistence.models import Category, Location, Role

ROLE_DESCRIPTIONS = {
    "STUDENT": "Campus student: reports items and submits claims.",
    "MODERATOR": "Campus moderator: verifies claims and records recoveries.",
}


def seed_reference_data(session: Session, campus: dict) -> dict[str, int]:
    """Upsert roles, categories, zones and locations by deterministic UUIDv5. Returns created counts."""
    created = {"roles": 0, "categories": 0, "zones": 0, "locations": 0}

    for name, desc in ROLE_DESCRIPTIONS.items():
        rid = seed_id("role", name)
        if session.get(Role, rid) is None:
            session.add(Role(role_id=rid, name=name, description=desc))
            created["roles"] += 1

    for cat in campus["categories"]:
        cid = seed_id("category", cat["slug"])
        row = session.get(Category, cid)
        if row is None:
            session.add(Category(category_id=cid, slug=cat["slug"], name=cat["name"], is_active=True))
            created["categories"] += 1
        # Existing rows are never renamed automatically (contract §16).

    session.flush()

    for zone in campus["zones"]:
        zid = seed_id("location", zone["slug"])
        if session.get(Location, zid) is None:
            session.add(Location(location_id=zid, slug=zone["slug"], name=zone["name"], is_zone=True, zone_id=None, is_active=True))
            created["zones"] += 1
    session.flush()

    for loc in campus["locations"]:
        lid = seed_id("location", loc["slug"])
        if session.get(Location, lid) is None:
            session.add(
                Location(
                    location_id=lid, slug=loc["slug"], name=loc["name"], is_zone=False,
                    zone_id=seed_id("location", loc["zone_slug"]), is_active=True,
                )
            )
            created["locations"] += 1
    session.flush()
    return created


def student_role_id():
    return seed_id("role", "STUDENT")


def moderator_role_id():
    return seed_id("role", "MODERATOR")


def role_ids(session: Session) -> dict[str, object]:
    return {r.name: r.role_id for r in session.scalars(select(Role))}
