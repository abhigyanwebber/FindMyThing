"""SQLAlchemy models mirroring IMPLEMENTATION_CONTRACTS Â§20/Â§26.

The authoritative DDL (guard columns, filtered indexes, trigger, view) lives in the Alembic
migration; these models are used for queries and must stay in sync with it.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    ForeignKey,
    Integer,
    Numeric,
    String,
    TypeDecorator,
    Unicode,
    UnicodeText,
)
from sqlalchemy.dialects.mssql import BINARY, DATETIME2, UNIQUEIDENTIFIER
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class UtcDateTime(TypeDecorator):
    """datetime2(3) storing naive UTC; always returns tz-aware UTC datetimes."""

    impl = DATETIME2(precision=3)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is not None:
            value = value.astimezone(dt.timezone.utc).replace(tzinfo=None)
        return value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=dt.timezone.utc)


UUID = UNIQUEIDENTIFIER(as_uuid=True)


class Base(DeclarativeBase):
    pass


class Role(Base):
    __tablename__ = "roles"
    role_id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True)
    name: Mapped[str] = mapped_column(String(16), unique=True)
    description: Mapped[str | None] = mapped_column(Unicode(200))


class User(Base):
    __tablename__ = "users"
    user_id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True)
    role_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("roles.role_id"))
    display_name: Mapped[str] = mapped_column(Unicode(80))
    email_normalized: Mapped[str] = mapped_column(Unicode(254), unique=True)
    password_hash: Mapped[str] = mapped_column(Unicode(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at_utc: Mapped[dt.datetime] = mapped_column(UtcDateTime)
    updated_at_utc: Mapped[dt.datetime] = mapped_column(UtcDateTime)


class SessionRow(Base):
    __tablename__ = "sessions"
    session_token_hash: Mapped[bytes] = mapped_column(BINARY(32), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("users.user_id"))
    csrf_token_hash: Mapped[bytes] = mapped_column(BINARY(32))
    created_at_utc: Mapped[dt.datetime] = mapped_column(UtcDateTime)
    expires_at_utc: Mapped[dt.datetime] = mapped_column(UtcDateTime)
    last_seen_at_utc: Mapped[dt.datetime] = mapped_column(UtcDateTime)
    revoked_at_utc: Mapped[dt.datetime | None] = mapped_column(UtcDateTime)
    user_agent_summary: Mapped[str | None] = mapped_column(Unicode(256))


class Category(Base):
    __tablename__ = "categories"
    category_id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(Unicode(80), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Location(Base):
    __tablename__ = "locations"
    location_id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(Unicode(120), unique=True)
    is_zone: Mapped[bool] = mapped_column(Boolean, default=False)
    zone_id: Mapped[uuid.UUID | None] = mapped_column(UUID, ForeignKey("locations.location_id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Report(Base):
    __tablename__ = "reports"
    report_id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True)
    reporter_user_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("users.user_id"))
    report_type: Mapped[str] = mapped_column(String(8))
    category_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("categories.category_id"))
    location_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("locations.location_id"))
    title: Mapped[str] = mapped_column(Unicode(120))
    description: Mapped[str] = mapped_column(Unicode(2000))
    occurred_on: Mapped[dt.date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16))
    status_reason_code: Mapped[str | None] = mapped_column(String(40))
    status_changed_at_utc: Mapped[dt.datetime] = mapped_column(UtcDateTime)
    created_at_utc: Mapped[dt.datetime] = mapped_column(UtcDateTime)
    updated_at_utc: Mapped[dt.datetime] = mapped_column(UtcDateTime)
    version: Mapped[int] = mapped_column(Integer, default=1)
    matching_version: Mapped[int] = mapped_column(Integer, default=1)


class Attachment(Base):
    __tablename__ = "attachments"
    attachment_id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True)
    report_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("reports.report_id"))
    uploaded_by_user_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("users.user_id"))
    attachment_type: Mapped[str] = mapped_column(String(20))
    blob_key: Mapped[str] = mapped_column(Unicode(512), unique=True)
    original_filename: Mapped[str] = mapped_column(Unicode(255))
    content_type: Mapped[str] = mapped_column(String(32))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    upload_status: Mapped[str] = mapped_column(String(16))
    created_at_utc: Mapped[dt.datetime] = mapped_column(UtcDateTime)
    deleted_at_utc: Mapped[dt.datetime | None] = mapped_column(UtcDateTime)
    purge_after_utc: Mapped[dt.datetime | None] = mapped_column(UtcDateTime)


class Match(Base):
    __tablename__ = "matches"
    match_id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True)
    lost_report_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("reports.report_id"))
    found_report_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("reports.report_id"))
    score = mapped_column(Numeric(5, 2))
    category_score = mapped_column(Numeric(5, 2))
    location_score = mapped_column(Numeric(5, 2))
    date_score = mapped_column(Numeric(5, 2))
    keyword_score = mapped_column(Numeric(5, 2))
    explanation: Mapped[str] = mapped_column(UnicodeText)
    algorithm_version: Mapped[str] = mapped_column(String(16))
    calculated_at_utc: Mapped[dt.datetime] = mapped_column(UtcDateTime)
    lost_report_matching_version: Mapped[int] = mapped_column(Integer)
    found_report_matching_version: Mapped[int] = mapped_column(Integer)
    match_status: Mapped[str] = mapped_column(String(16))
    invalidated_at_utc: Mapped[dt.datetime | None] = mapped_column(UtcDateTime)
    invalidation_reason: Mapped[str | None] = mapped_column(String(64))


class Claim(Base):
    __tablename__ = "claims"
    claim_id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True)
    found_report_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("reports.report_id"))
    claimant_user_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("users.user_id"))
    lost_report_id: Mapped[uuid.UUID | None] = mapped_column(UUID, ForeignKey("reports.report_id"))
    claim_statement: Mapped[str] = mapped_column(Unicode(2000))
    status: Mapped[str] = mapped_column(String(16))
    version: Mapped[int] = mapped_column(Integer, default=1)
    found_report_version_at_submission: Mapped[int] = mapped_column(Integer)
    lost_report_version_at_submission: Mapped[int | None] = mapped_column(Integer)
    report_snapshot: Mapped[str] = mapped_column(UnicodeText)
    created_at_utc: Mapped[dt.datetime] = mapped_column(UtcDateTime)
    updated_at_utc: Mapped[dt.datetime] = mapped_column(UtcDateTime)
    status_changed_at_utc: Mapped[dt.datetime] = mapped_column(UtcDateTime)
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID, ForeignKey("users.user_id"))
    reviewed_at_utc: Mapped[dt.datetime | None] = mapped_column(UtcDateTime)
    decision_reason_code: Mapped[str | None] = mapped_column(String(40))
    decision_note: Mapped[str | None] = mapped_column(Unicode(1000))
    information_request_note: Mapped[str | None] = mapped_column(Unicode(1000))
    information_requested_at_utc: Mapped[dt.datetime | None] = mapped_column(UtcDateTime)


class MatchingJob(Base):
    __tablename__ = "matching_jobs"
    job_id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True)
    report_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("reports.report_id"))
    report_matching_version: Mapped[int] = mapped_column(Integer)
    algorithm_version: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at_utc: Mapped[dt.datetime | None] = mapped_column(UtcDateTime)
    lease_expires_at_utc: Mapped[dt.datetime | None] = mapped_column(UtcDateTime)
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    created_at_utc: Mapped[dt.datetime] = mapped_column(UtcDateTime)
    updated_at_utc: Mapped[dt.datetime] = mapped_column(UtcDateTime)


class ReportStatusHistory(Base):
    __tablename__ = "report_status_history"
    history_id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True)
    report_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("reports.report_id"))
    old_status: Mapped[str] = mapped_column(String(16))
    new_status: Mapped[str] = mapped_column(String(16))
    changed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID, ForeignKey("users.user_id"))
    changed_at_utc: Mapped[dt.datetime] = mapped_column(UtcDateTime)
    reason_code: Mapped[str] = mapped_column(String(40))
    correlation_id: Mapped[str] = mapped_column(String(128))


class ClaimStatusHistory(Base):
    __tablename__ = "claim_status_history"
    history_id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True)
    claim_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("claims.claim_id"))
    old_status: Mapped[str] = mapped_column(String(16))
    new_status: Mapped[str] = mapped_column(String(16))
    changed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID, ForeignKey("users.user_id"))
    changed_at_utc: Mapped[dt.datetime] = mapped_column(UtcDateTime)
    reason_code: Mapped[str] = mapped_column(String(40))
    note: Mapped[str | None] = mapped_column(Unicode(1000))
    correlation_id: Mapped[str] = mapped_column(String(128))


class ActivityLog(Base):
    __tablename__ = "activity_logs"
    activity_id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID, ForeignKey("users.user_id"))
    event_type: Mapped[str] = mapped_column(String(64))
    target_type: Mapped[str] = mapped_column(String(32))
    target_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    created_at_utc: Mapped[dt.datetime] = mapped_column(UtcDateTime)
    outcome: Mapped[str] = mapped_column(String(16))
    correlation_id: Mapped[str] = mapped_column(String(128))
    metadata_json: Mapped[str | None] = mapped_column("metadata", UnicodeText)


class Recovery(Base):
    __tablename__ = "recoveries"
    recovery_id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True)
    claim_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("claims.claim_id"))
    found_report_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("reports.report_id"))
    lost_report_id: Mapped[uuid.UUID | None] = mapped_column(UUID, ForeignKey("reports.report_id"))
    status: Mapped[str] = mapped_column(String(16))
    completed_by_moderator_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("users.user_id"))
    completed_at_utc: Mapped[dt.datetime] = mapped_column(UtcDateTime)
    voided_by_moderator_id: Mapped[uuid.UUID | None] = mapped_column(UUID, ForeignKey("users.user_id"))
    voided_at_utc: Mapped[dt.datetime | None] = mapped_column(UtcDateTime)
    void_reason_code: Mapped[str | None] = mapped_column(String(40))
    void_note: Mapped[str | None] = mapped_column(Unicode(1000))
    found_prior_status: Mapped[str] = mapped_column(String(16))
    found_prior_version: Mapped[int] = mapped_column(Integer)
    found_post_version: Mapped[int] = mapped_column(Integer)
    lost_prior_status: Mapped[str | None] = mapped_column(String(16))
    lost_prior_version: Mapped[int | None] = mapped_column(Integer)
    lost_post_version: Mapped[int | None] = mapped_column(Integer)


class ClaimEvidence(Base):
    __tablename__ = "claim_evidence"
    evidence_id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True)
    claim_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("claims.claim_id"))
    uploaded_by_user_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("users.user_id"))
    blob_key: Mapped[str] = mapped_column(Unicode(512), unique=True)
    original_filename: Mapped[str] = mapped_column(Unicode(255))
    content_type: Mapped[str] = mapped_column(String(32))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    upload_status: Mapped[str] = mapped_column(String(16))
    uploaded_at_utc: Mapped[dt.datetime] = mapped_column(UtcDateTime)
    description: Mapped[str | None] = mapped_column(Unicode(500))
    deleted_at_utc: Mapped[dt.datetime | None] = mapped_column(UtcDateTime)
    purge_after_utc: Mapped[dt.datetime | None] = mapped_column(UtcDateTime)


class RateLimitCounter(Base):
    __tablename__ = "rate_limit_counters"
    counter_id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True)
    key_hash: Mapped[bytes] = mapped_column(BINARY(32))
    window_start_utc: Mapped[dt.datetime] = mapped_column(UtcDateTime)
    window_seconds: Mapped[int] = mapped_column(Integer)
    count: Mapped[int] = mapped_column(Integer)
    expires_at_utc: Mapped[dt.datetime] = mapped_column(UtcDateTime)

