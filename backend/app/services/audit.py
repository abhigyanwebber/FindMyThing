"""Audit logging with an event-type registry and metadata allowlist (contract §5).

Never log claim statements/evidence, passwords, tokens, Blob keys, original filenames or raw user content.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.security import new_id, utcnow
from app.persistence.models import ActivityLog

EVENT_TYPES = frozenset(
    """AUTH_REGISTERED AUTH_LOGIN_SUCCEEDED AUTH_LOGIN_FAILED AUTH_LOGOUT USER_DEACTIVATED REPORT_CREATED
    REPORT_UPDATED REPORT_WITHDRAWN REPORT_CLOSED REPORT_REOPENED REPORT_MODERATOR_CORRECTED
    REPORT_PHOTO_UPLOADED REPORT_PHOTO_DELETED MATCH_JOB_QUEUED MATCH_JOB_SUCCEEDED MATCH_JOB_FAILED
    MATCH_DISMISSED CLAIM_SUBMITTED CLAIM_VERIFIED CLAIM_REJECTED CLAIM_VERIFICATION_REVOKED
    CLAIM_CANCELLED CLAIM_INFORMATION_REQUESTED CLAIM_EVIDENCE_UPLOADED CLAIM_EVIDENCE_DELETED
    RECOVERY_COMPLETED RECOVERY_VOIDED MODERATOR_CLAIM_DETAIL_ACCESSED MODERATOR_EVIDENCE_ACCESSED
    RATE_LIMIT_TRIGGERED RETENTION_CLEANUP MATCH_JOB_RETRIED""".split()
)

# Report moderator-action notes are the only free text allowed in metadata (contract §5).
ALLOWED_METADATA_KEYS = frozenset(
    """reason_code old_status new_status status report_type job_id report_id claim_id recovery_id match_id
    attempt_count error_code algorithm_version matching_version candidate_count potential_count
    old_score old_factors old_match_status old_lost_matching_version old_found_matching_version
    limit_name changed_fields resolved_reports reopened_reports reports_requiring_reconciliation
    rejected_competing_claims deleted_count purged_attachments purged_evidence purged_logs
    orphan_blobs_removed failures operator decision_note role""".split()
)

OUTCOMES = frozenset({"SUCCESS", "FAILURE", "DENIED", "SYSTEM"})


def sanitize_metadata(metadata: dict[str, Any] | None) -> dict[str, Any] | None:
    if not metadata:
        return None
    clean: dict[str, Any] = {}
    for key, value in metadata.items():
        if key not in ALLOWED_METADATA_KEYS:
            continue
        if isinstance(value, (uuid.UUID,)):
            value = str(value)
        elif isinstance(value, (list, tuple)):
            value = [str(v) if isinstance(v, uuid.UUID) else v for v in value]
        if key == "decision_note" and isinstance(value, str):
            value = value[:1000]
        clean[key] = value
    return clean or None


def log_event(
    db: Session, *, event_type: str, outcome: str, correlation_id: str, actor_user_id: uuid.UUID | None = None,
    target_type: str = "NONE", target_id: uuid.UUID | None = None, metadata: dict[str, Any] | None = None,
) -> None:
    if event_type not in EVENT_TYPES:
        raise ValueError(f"Unknown audit event type: {event_type}")
    if outcome not in OUTCOMES:
        raise ValueError(f"Unknown audit outcome: {outcome}")
    clean = sanitize_metadata(metadata)
    db.add(
        ActivityLog(
            activity_id=new_id(), actor_user_id=actor_user_id, event_type=event_type, target_type=target_type,
            target_id=target_id, created_at_utc=utcnow(), outcome=outcome, correlation_id=correlation_id[:128],
            metadata_json=json.dumps(clean, default=str) if clean else None,
        )
    )
    db.flush()
