"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-10

Authoritative DDL per IMPLEMENTATION_CONTRACTS §6, §20, §26 and Blueprint §3.
"""

from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

STMTS = [
    # ---- roles / users / sessions -------------------------------------------------------
    """CREATE TABLE roles (
        role_id uniqueidentifier NOT NULL CONSTRAINT pk_roles PRIMARY KEY,
        name varchar(16) NOT NULL CONSTRAINT uq_roles_name UNIQUE,
        description nvarchar(200) NULL,
        CONSTRAINT ck_roles_name CHECK (name IN ('STUDENT','MODERATOR'))
    )""",
    """CREATE TABLE users (
        user_id uniqueidentifier NOT NULL CONSTRAINT pk_users PRIMARY KEY,
        role_id uniqueidentifier NOT NULL CONSTRAINT fk_users_role REFERENCES roles(role_id),
        display_name nvarchar(80) NOT NULL,
        email_normalized nvarchar(254) NOT NULL CONSTRAINT uq_users_email UNIQUE,
        password_hash nvarchar(255) NOT NULL,
        is_active bit NOT NULL CONSTRAINT df_users_active DEFAULT 1,
        created_at_utc datetime2(3) NOT NULL,
        updated_at_utc datetime2(3) NOT NULL
    )""",
    """CREATE TABLE sessions (
        session_token_hash binary(32) NOT NULL CONSTRAINT pk_sessions PRIMARY KEY,
        user_id uniqueidentifier NOT NULL CONSTRAINT fk_sessions_user REFERENCES users(user_id),
        csrf_token_hash binary(32) NOT NULL,
        created_at_utc datetime2(3) NOT NULL,
        expires_at_utc datetime2(3) NOT NULL,
        last_seen_at_utc datetime2(3) NOT NULL,
        revoked_at_utc datetime2(3) NULL,
        user_agent_summary nvarchar(256) NULL
    )""",
    "CREATE INDEX ix_sessions_user_expires ON sessions(user_id, expires_at_utc)",
    # ---- reference data ------------------------------------------------------------------
    """CREATE TABLE categories (
        category_id uniqueidentifier NOT NULL CONSTRAINT pk_categories PRIMARY KEY,
        slug varchar(64) NOT NULL CONSTRAINT uq_categories_slug UNIQUE,
        name nvarchar(80) NOT NULL CONSTRAINT uq_categories_name UNIQUE,
        is_active bit NOT NULL CONSTRAINT df_categories_active DEFAULT 1
    )""",
    """CREATE TABLE locations (
        location_id uniqueidentifier NOT NULL CONSTRAINT pk_locations PRIMARY KEY,
        slug varchar(64) NOT NULL CONSTRAINT uq_locations_slug UNIQUE,
        name nvarchar(120) NOT NULL CONSTRAINT uq_locations_name UNIQUE,
        is_zone bit NOT NULL CONSTRAINT df_locations_is_zone DEFAULT 0,
        zone_id uniqueidentifier NULL CONSTRAINT fk_locations_zone REFERENCES locations(location_id),
        is_active bit NOT NULL CONSTRAINT df_locations_active DEFAULT 1,
        CONSTRAINT ck_locations_zone_shape CHECK (
            (is_zone = 1 AND zone_id IS NULL) OR (is_zone = 0 AND zone_id IS NOT NULL))
    )""",
    # ---- reports -------------------------------------------------------------------------
    """CREATE TABLE reports (
        report_id uniqueidentifier NOT NULL CONSTRAINT pk_reports PRIMARY KEY,
        reporter_user_id uniqueidentifier NOT NULL CONSTRAINT fk_reports_user REFERENCES users(user_id),
        report_type varchar(8) NOT NULL,
        category_id uniqueidentifier NOT NULL CONSTRAINT fk_reports_category REFERENCES categories(category_id),
        location_id uniqueidentifier NOT NULL CONSTRAINT fk_reports_location REFERENCES locations(location_id),
        title nvarchar(120) NOT NULL,
        description nvarchar(2000) NOT NULL,
        occurred_on date NOT NULL,
        status varchar(16) NOT NULL,
        status_reason_code varchar(40) NULL,
        status_changed_at_utc datetime2(3) NOT NULL,
        created_at_utc datetime2(3) NOT NULL,
        updated_at_utc datetime2(3) NOT NULL,
        version int NOT NULL CONSTRAINT df_reports_version DEFAULT 1,
        matching_version int NOT NULL CONSTRAINT df_reports_mversion DEFAULT 1,
        CONSTRAINT ck_reports_type CHECK (report_type IN ('LOST','FOUND')),
        CONSTRAINT ck_reports_status CHECK (status IN ('ACTIVE','RESOLVED','WITHDRAWN','CLOSED')),
        CONSTRAINT ck_reports_versions CHECK (version >= 1 AND matching_version >= 1)
    )""",
    "CREATE INDEX ix_reports_browse ON reports(report_type, status, created_at_utc)",
    "CREATE INDEX ix_reports_status_type ON reports(status, report_type, created_at_utc)",
    "CREATE INDEX ix_reports_cat_loc_date ON reports(category_id, location_id, occurred_on)",
    "CREATE INDEX ix_reports_reporter ON reports(reporter_user_id, created_at_utc)",
    # ---- attachments ---------------------------------------------------------------------
    """CREATE TABLE attachments (
        attachment_id uniqueidentifier NOT NULL CONSTRAINT pk_attachments PRIMARY KEY,
        report_id uniqueidentifier NOT NULL CONSTRAINT fk_attachments_report REFERENCES reports(report_id),
        uploaded_by_user_id uniqueidentifier NOT NULL CONSTRAINT fk_attachments_user REFERENCES users(user_id),
        attachment_type varchar(20) NOT NULL,
        blob_key nvarchar(512) NOT NULL CONSTRAINT uq_attachments_blob UNIQUE,
        original_filename nvarchar(255) NOT NULL,
        content_type varchar(32) NOT NULL,
        size_bytes bigint NOT NULL,
        upload_status varchar(16) NOT NULL,
        created_at_utc datetime2(3) NOT NULL,
        deleted_at_utc datetime2(3) NULL,
        purge_after_utc datetime2(3) NULL,
        CONSTRAINT ck_attachments_type CHECK (attachment_type IN ('REPORT_PHOTO')),
        CONSTRAINT ck_attachments_status CHECK (upload_status IN ('ACTIVE','DELETED','PENDING_CLEANUP')),
        CONSTRAINT ck_attachments_size CHECK (size_bytes BETWEEN 1 AND 5000000),
        CONSTRAINT ck_attachments_ctype CHECK (content_type IN ('image/jpeg','image/png','image/webp'))
    )""",
    """CREATE UNIQUE INDEX ux_attachments_one_active_photo ON attachments(report_id)
       WHERE attachment_type = 'REPORT_PHOTO' AND upload_status = 'ACTIVE' AND deleted_at_utc IS NULL""",
    "CREATE INDEX ix_attachments_report ON attachments(report_id, created_at_utc)",
    # ---- matches -------------------------------------------------------------------------
    """CREATE TABLE matches (
        match_id uniqueidentifier NOT NULL CONSTRAINT pk_matches PRIMARY KEY,
        lost_report_id uniqueidentifier NOT NULL CONSTRAINT fk_matches_lost REFERENCES reports(report_id),
        found_report_id uniqueidentifier NOT NULL CONSTRAINT fk_matches_found REFERENCES reports(report_id),
        score decimal(5,2) NOT NULL,
        category_score decimal(5,2) NOT NULL,
        location_score decimal(5,2) NOT NULL,
        date_score decimal(5,2) NOT NULL,
        keyword_score decimal(5,2) NOT NULL,
        explanation nvarchar(max) NOT NULL,
        algorithm_version varchar(16) NOT NULL,
        calculated_at_utc datetime2(3) NOT NULL,
        lost_report_matching_version int NOT NULL,
        found_report_matching_version int NOT NULL,
        match_status varchar(16) NOT NULL,
        invalidated_at_utc datetime2(3) NULL,
        invalidation_reason varchar(64) NULL,
        CONSTRAINT uq_matches_pair UNIQUE (lost_report_id, found_report_id, algorithm_version),
        CONSTRAINT ck_matches_distinct CHECK (lost_report_id <> found_report_id),
        CONSTRAINT ck_matches_status CHECK (match_status IN ('POTENTIAL','SUPPRESSED','INVALIDATED','DISMISSED')),
        CONSTRAINT ck_matches_scores CHECK (
            score BETWEEN 0 AND 100 AND category_score BETWEEN 0 AND 100 AND location_score BETWEEN 0 AND 100
            AND date_score BETWEEN 0 AND 100 AND keyword_score BETWEEN 0 AND 100),
        CONSTRAINT ck_matches_json CHECK (ISJSON(explanation) = 1)
    )""",
    "CREATE INDEX ix_matches_lost_score ON matches(lost_report_id, score DESC)",
    "CREATE INDEX ix_matches_found_score ON matches(found_report_id, score DESC)",
    # ---- claims --------------------------------------------------------------------------
    """CREATE TABLE claims (
        claim_id uniqueidentifier NOT NULL CONSTRAINT pk_claims PRIMARY KEY,
        found_report_id uniqueidentifier NOT NULL CONSTRAINT fk_claims_found REFERENCES reports(report_id),
        claimant_user_id uniqueidentifier NOT NULL CONSTRAINT fk_claims_claimant REFERENCES users(user_id),
        lost_report_id uniqueidentifier NULL CONSTRAINT fk_claims_lost REFERENCES reports(report_id),
        claim_statement nvarchar(2000) NOT NULL,
        status varchar(16) NOT NULL,
        version int NOT NULL CONSTRAINT df_claims_version DEFAULT 1,
        found_report_version_at_submission int NOT NULL,
        lost_report_version_at_submission int NULL,
        report_snapshot nvarchar(max) NOT NULL,
        created_at_utc datetime2(3) NOT NULL,
        updated_at_utc datetime2(3) NOT NULL,
        status_changed_at_utc datetime2(3) NOT NULL,
        reviewed_by_user_id uniqueidentifier NULL CONSTRAINT fk_claims_reviewer REFERENCES users(user_id),
        reviewed_at_utc datetime2(3) NULL,
        decision_reason_code varchar(40) NULL,
        decision_note nvarchar(1000) NULL,
        information_request_note nvarchar(1000) NULL,
        information_requested_at_utc datetime2(3) NULL,
        CONSTRAINT ck_claims_status CHECK (status IN ('PENDING','VERIFIED','RECOVERED','REJECTED','CANCELLED')),
        CONSTRAINT ck_claims_version CHECK (version >= 1),
        CONSTRAINT ck_claims_snapshot CHECK (ISJSON(report_snapshot) = 1),
        CONSTRAINT ck_claims_distinct CHECK (lost_report_id IS NULL OR lost_report_id <> found_report_id)
    )""",
    "CREATE UNIQUE INDEX ux_claims_active_claimant_found ON claims(claimant_user_id, found_report_id) WHERE status IN ('PENDING','VERIFIED')",
    "CREATE UNIQUE INDEX ux_claims_active_found ON claims(found_report_id) WHERE status IN ('VERIFIED','RECOVERED')",
    "CREATE UNIQUE INDEX ux_claims_active_lost ON claims(lost_report_id) WHERE status IN ('VERIFIED','RECOVERED') AND lost_report_id IS NOT NULL",
    "CREATE INDEX ix_claims_found_status ON claims(found_report_id, status, created_at_utc)",
    "CREATE INDEX ix_claims_lost ON claims(lost_report_id) WHERE lost_report_id IS NOT NULL",
    "CREATE INDEX ix_claims_claimant ON claims(claimant_user_id, created_at_utc)",
    "CREATE INDEX ix_claims_status ON claims(status, created_at_utc)",
    # ---- matching outbox -----------------------------------------------------------------
    """CREATE TABLE matching_jobs (
        job_id uniqueidentifier NOT NULL CONSTRAINT pk_matching_jobs PRIMARY KEY,
        report_id uniqueidentifier NOT NULL CONSTRAINT fk_mjobs_report REFERENCES reports(report_id),
        report_matching_version int NOT NULL,
        algorithm_version varchar(16) NOT NULL,
        status varchar(16) NOT NULL,
        attempt_count int NOT NULL CONSTRAINT df_mjobs_attempt DEFAULT 0,
        next_attempt_at_utc datetime2(3) NULL,
        lease_expires_at_utc datetime2(3) NULL,
        last_error_code varchar(64) NULL,
        created_at_utc datetime2(3) NOT NULL,
        updated_at_utc datetime2(3) NOT NULL,
        CONSTRAINT uq_mjobs_idem UNIQUE (report_id, report_matching_version, algorithm_version),
        CONSTRAINT ck_mjobs_status CHECK (status IN ('PENDING','PROCESSING','SUCCEEDED','SUPERSEDED','DEAD')),
        CONSTRAINT ck_mjobs_attempt CHECK (attempt_count >= 0),
        CONSTRAINT ck_mjobs_next CHECK (status <> 'PENDING' OR next_attempt_at_utc IS NOT NULL)
    )""",
    "CREATE INDEX ix_mjobs_due ON matching_jobs(status, next_attempt_at_utc, lease_expires_at_utc)",
    # ---- histories / audit ---------------------------------------------------------------
    """CREATE TABLE report_status_history (
        history_id uniqueidentifier NOT NULL CONSTRAINT pk_rsh PRIMARY KEY,
        report_id uniqueidentifier NOT NULL CONSTRAINT fk_rsh_report REFERENCES reports(report_id),
        old_status varchar(16) NOT NULL,
        new_status varchar(16) NOT NULL,
        changed_by_user_id uniqueidentifier NULL CONSTRAINT fk_rsh_user REFERENCES users(user_id),
        changed_at_utc datetime2(3) NOT NULL,
        reason_code varchar(40) NOT NULL,
        correlation_id varchar(128) NOT NULL
    )""",
    "CREATE INDEX ix_rsh_report ON report_status_history(report_id, changed_at_utc)",
    """CREATE TABLE claim_status_history (
        history_id uniqueidentifier NOT NULL CONSTRAINT pk_csh PRIMARY KEY,
        claim_id uniqueidentifier NOT NULL CONSTRAINT fk_csh_claim REFERENCES claims(claim_id),
        old_status varchar(16) NOT NULL,
        new_status varchar(16) NOT NULL,
        changed_by_user_id uniqueidentifier NULL CONSTRAINT fk_csh_user REFERENCES users(user_id),
        changed_at_utc datetime2(3) NOT NULL,
        reason_code varchar(40) NOT NULL,
        note nvarchar(1000) NULL,
        correlation_id varchar(128) NOT NULL
    )""",
    "CREATE INDEX ix_csh_claim ON claim_status_history(claim_id, changed_at_utc)",
    """CREATE TABLE activity_logs (
        activity_id uniqueidentifier NOT NULL CONSTRAINT pk_activity PRIMARY KEY,
        actor_user_id uniqueidentifier NULL CONSTRAINT fk_activity_user REFERENCES users(user_id),
        event_type varchar(64) NOT NULL,
        target_type varchar(32) NOT NULL,
        target_id uniqueidentifier NULL,
        created_at_utc datetime2(3) NOT NULL,
        outcome varchar(16) NOT NULL,
        correlation_id varchar(128) NOT NULL,
        metadata nvarchar(max) NULL,
        CONSTRAINT ck_activity_json CHECK (metadata IS NULL OR ISJSON(metadata) = 1)
    )""",
    "CREATE INDEX ix_activity_time ON activity_logs(created_at_utc, event_type)",
    # ---- recoveries ----------------------------------------------------------------------
    """CREATE TABLE recoveries (
        recovery_id uniqueidentifier NOT NULL CONSTRAINT pk_recoveries PRIMARY KEY,
        claim_id uniqueidentifier NOT NULL CONSTRAINT fk_rec_claim REFERENCES claims(claim_id),
        found_report_id uniqueidentifier NOT NULL CONSTRAINT fk_rec_found REFERENCES reports(report_id),
        lost_report_id uniqueidentifier NULL CONSTRAINT fk_rec_lost REFERENCES reports(report_id),
        status varchar(16) NOT NULL,
        completed_by_moderator_id uniqueidentifier NOT NULL CONSTRAINT fk_rec_completed_by REFERENCES users(user_id),
        completed_at_utc datetime2(3) NOT NULL,
        voided_by_moderator_id uniqueidentifier NULL CONSTRAINT fk_rec_voided_by REFERENCES users(user_id),
        voided_at_utc datetime2(3) NULL,
        void_reason_code varchar(40) NULL,
        void_note nvarchar(1000) NULL,
        found_prior_status varchar(16) NOT NULL,
        found_prior_version int NOT NULL,
        found_post_version int NOT NULL,
        lost_prior_status varchar(16) NULL,
        lost_prior_version int NULL,
        lost_post_version int NULL,
        CONSTRAINT ck_rec_status CHECK (status IN ('COMPLETED','VOIDED'))
    )""",
    "CREATE UNIQUE INDEX ux_rec_claim ON recoveries(claim_id) WHERE status = 'COMPLETED'",
    "CREATE UNIQUE INDEX ux_rec_found ON recoveries(found_report_id) WHERE status = 'COMPLETED'",
    "CREATE UNIQUE INDEX ux_rec_lost ON recoveries(lost_report_id) WHERE status = 'COMPLETED' AND lost_report_id IS NOT NULL",
    # ---- claim evidence ------------------------------------------------------------------
    """CREATE TABLE claim_evidence (
        evidence_id uniqueidentifier NOT NULL CONSTRAINT pk_claim_evidence PRIMARY KEY,
        claim_id uniqueidentifier NOT NULL CONSTRAINT fk_evidence_claim REFERENCES claims(claim_id),
        uploaded_by_user_id uniqueidentifier NOT NULL CONSTRAINT fk_evidence_user REFERENCES users(user_id),
        blob_key nvarchar(512) NOT NULL CONSTRAINT uq_evidence_blob UNIQUE,
        original_filename nvarchar(255) NOT NULL,
        content_type varchar(32) NOT NULL,
        size_bytes bigint NOT NULL,
        upload_status varchar(16) NOT NULL,
        uploaded_at_utc datetime2(3) NOT NULL,
        description nvarchar(500) NULL,
        deleted_at_utc datetime2(3) NULL,
        purge_after_utc datetime2(3) NULL,
        CONSTRAINT ck_evidence_status CHECK (upload_status IN ('ACTIVE','DELETED','PENDING_CLEANUP')),
        CONSTRAINT ck_evidence_size CHECK (size_bytes BETWEEN 1 AND 5000000),
        CONSTRAINT ck_evidence_ctype CHECK (content_type IN ('image/jpeg','image/png','image/webp'))
    )""",
    "CREATE INDEX ix_evidence_claim ON claim_evidence(claim_id, uploaded_at_utc)",
    # ---- rate limiting -------------------------------------------------------------------
    """CREATE TABLE rate_limit_counters (
        counter_id uniqueidentifier NOT NULL CONSTRAINT pk_rate_limit PRIMARY KEY,
        key_hash binary(32) NOT NULL,
        window_start_utc datetime2(3) NOT NULL,
        window_seconds int NOT NULL,
        count int NOT NULL,
        expires_at_utc datetime2(3) NOT NULL,
        CONSTRAINT uq_rate_limit UNIQUE (key_hash, window_start_utc, window_seconds),
        CONSTRAINT ck_rate_limit CHECK (count >= 0 AND window_seconds > 0)
    )""",
    "CREATE INDEX ix_rate_limit_expiry ON rate_limit_counters(expires_at_utc)",
    # ---- report status-history trigger (frozen D-021) ------------------------------------
    """CREATE TRIGGER trg_report_status_history ON reports AFTER UPDATE AS
    BEGIN
        SET NOCOUNT ON;
        IF NOT UPDATE(status) RETURN;
        INSERT INTO report_status_history
            (history_id, report_id, old_status, new_status, changed_by_user_id, changed_at_utc, reason_code, correlation_id)
        SELECT NEWID(), i.report_id, d.status, i.status,
               TRY_CAST(CONVERT(nvarchar(36), SESSION_CONTEXT(N'actor_id')) AS uniqueidentifier),
               SYSUTCDATETIME(),
               COALESCE(CONVERT(varchar(40), SESSION_CONTEXT(N'reason_code')), 'UNSPECIFIED'),
               COALESCE(CONVERT(varchar(128), SESSION_CONTEXT(N'correlation_id')), 'none')
        FROM inserted i JOIN deleted d ON d.report_id = i.report_id
        WHERE i.status <> d.status;
    END""",
    # ---- analytics views (contract §12/§22; no claimant identity, statements, or evidence) --
    """CREATE VIEW vw_recovery_analytics AS
    SELECT r.report_id, r.report_type, r.status, c.name AS category, l.name AS location, z.name AS zone,
           r.created_at_utc, r.occurred_on,
           rec.completed_at_utc AS recovered_at_utc,
           CASE WHEN r.report_type = 'FOUND' AND rec.recovery_id IS NOT NULL THEN 1 ELSE 0 END AS is_recovered,
           CASE WHEN r.report_type = 'FOUND' AND rec.recovery_id IS NOT NULL
                THEN ROUND(DATEDIFF(second, r.created_at_utc, rec.completed_at_utc) / 86400.0, 1) END AS days_to_recovery,
           (SELECT COUNT(*) FROM claims cl WHERE cl.found_report_id = r.report_id) AS claims_submitted
    FROM reports r
    JOIN categories c ON c.category_id = r.category_id
    JOIN locations l ON l.location_id = r.location_id
    LEFT JOIN locations z ON z.location_id = l.zone_id
    LEFT JOIN recoveries rec ON rec.found_report_id = r.report_id AND rec.status = 'COMPLETED'""",
    """CREATE VIEW vw_claim_transition_analytics AS
    SELECT h.history_id, h.changed_at_utc, h.new_status, h.reason_code, c.name AS category, l.name AS location
    FROM claim_status_history h
    JOIN claims cl ON cl.claim_id = h.claim_id
    JOIN reports r ON r.report_id = cl.found_report_id
    JOIN categories c ON c.category_id = r.category_id
    JOIN locations l ON l.location_id = r.location_id""",
]

DROP_ORDER = [
    "DROP VIEW IF EXISTS vw_claim_transition_analytics",
    "DROP VIEW IF EXISTS vw_recovery_analytics",
    "DROP TRIGGER IF EXISTS trg_report_status_history",
    "DROP TABLE IF EXISTS rate_limit_counters",
    "DROP TABLE IF EXISTS claim_evidence",
    "DROP TABLE IF EXISTS recoveries",
    "DROP TABLE IF EXISTS activity_logs",
    "DROP TABLE IF EXISTS claim_status_history",
    "DROP TABLE IF EXISTS report_status_history",
    "DROP TABLE IF EXISTS matching_jobs",
    "DROP TABLE IF EXISTS claims",
    "DROP TABLE IF EXISTS matches",
    "DROP TABLE IF EXISTS attachments",
    "DROP TABLE IF EXISTS reports",
    "DROP TABLE IF EXISTS locations",
    "DROP TABLE IF EXISTS categories",
    "DROP TABLE IF EXISTS sessions",
    "DROP TABLE IF EXISTS users",
    "DROP TABLE IF EXISTS roles",
]


def upgrade() -> None:
    for stmt in STMTS:
        op.execute(stmt)


def downgrade() -> None:
    # Destructive: only for controlled local rollback (contract §15).
    for stmt in DROP_ORDER:
        op.execute(stmt)
