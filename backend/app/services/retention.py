"""Attachment/evidence retention scheduling (contract §10). Purge = terminal transition + 90 days.

Cleanup execution (Blob deletion) lives in `app.services.cleanup`; this module only schedules/cancels.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.security import utcnow
from app.persistence.models import Attachment, ClaimEvidence

RETENTION = dt.timedelta(days=90)


def schedule_purge_for_report(db: Session, report_id: uuid.UUID, terminal_at: dt.datetime | None = None) -> None:
    due = (terminal_at or utcnow()) + RETENTION
    db.execute(
        update(Attachment)
        .where(Attachment.report_id == report_id, Attachment.upload_status == "ACTIVE", Attachment.deleted_at_utc.is_(None))
        .values(purge_after_utc=due)
    )


def cancel_purge_for_report(db: Session, report_id: uuid.UUID) -> None:
    db.execute(
        update(Attachment)
        .where(Attachment.report_id == report_id, Attachment.deleted_at_utc.is_(None))
        .values(purge_after_utc=None)
    )


def schedule_purge_for_claim(db: Session, claim_id: uuid.UUID, terminal_at: dt.datetime | None = None) -> None:
    due = (terminal_at or utcnow()) + RETENTION
    db.execute(
        update(ClaimEvidence)
        .where(ClaimEvidence.claim_id == claim_id, ClaimEvidence.upload_status == "ACTIVE", ClaimEvidence.deleted_at_utc.is_(None))
        .values(purge_after_utc=due)
    )


def cancel_purge_for_claim(db: Session, claim_id: uuid.UUID) -> None:
    db.execute(
        update(ClaimEvidence)
        .where(ClaimEvidence.claim_id == claim_id, ClaimEvidence.deleted_at_utc.is_(None))
        .values(purge_after_utc=None)
    )
