# FindMyThing — Implementation Contracts

**Status:** Specification closure v1.0 (frozen implementation contract)  
**Authority:** This document resolves implementation-level gaps identified in `IMPLEMENTATION_READINESS_AUDIT.md`. It does not alter the product scope or frozen state/matching/security invariants. Read with `ARCHITECTURE.md` and `BLUEPRINT.md`.

If a contradiction exists, precedence is: explicit owner instruction → `DECISIONS.md` → this implementation contract → `BLUEPRINT.md` → `ARCHITECTURE.md` → other docs/research. A genuine conflict must be reported; agents must not silently invent a resolution.

## 1. Global API conventions

- API base: `/api`; versioning is not added for this project.
- All routes except `GET /api/health`, `GET /api/health/ready`, `POST /api/auth/register`, and `POST /api/auth/login` require authentication. Public registration creates STUDENT only. Report browsing requires an authenticated user.
- All JSON responses use the direct resource shape described below; do not wrap success payloads in `{data: ...}`. Error responses use the common error envelope in §1.6.
- IDs are UUIDs serialized as lowercase canonical strings. SQL uses `uniqueidentifier`; Python uses `uuid.UUID`.
- Timestamps are UTC ISO 8601 strings with `Z`. Date-only domain values use `YYYY-MM-DD`.
- Lists use page-based pagination: `page` defaults to 1; `page_size` defaults to 20 and is clamped/rejected above 100 (reject with 422); `total` is exact count. Sort order is stable and explicitly defined per route. Response shape: `{ "items": [], "page": 1, "page_size": 20, "total": 0 }`.
- Unknown request fields are rejected (Pydantic `extra="forbid"`). Server-controlled fields cannot be mass-assigned.
- `request_id` is the canonical request correlation ID. Middleware creates/accepts a valid `X-Request-ID` (max 128 visible ASCII characters; otherwise generate UUID), returns it in response header `X-Request-ID`, and error body uses the same name. Database/audit `correlation_id` stores this same value.
- Success status: GET 200; create 201; successful action POST 200 unless it creates a new resource (201); delete attachment 204. No success body for 204.
- Error shape: `{ "error": { "code": "...", "message": "...", "request_id": "...", "field_errors": {"field": ["message"]} } }`. `field_errors` is omitted if none. Never expose stack traces, SQL messages, storage keys, or secrets.
- Mapping: 400 malformed body/invalid action, 401 unauthenticated, 403 forbidden, 404 missing or deliberately concealed resource, 409 state/version/concurrency conflict, 413 oversized file, 415 unsupported file type, 422 field/schema validation, 429 throttled, 500 generic internal error, 503 required dependency unavailable.

## 2. Validation and text rules

- `display_name`: trimmed, 1–80 Unicode characters; reject control characters other than ordinary whitespace; collapse consecutive whitespace to one space.
- `email`: 3–254 characters; trim and lowercase for `email_normalized`; syntactically valid email. No campus-domain restriction and no email verification in F1–F6. Password reset/change endpoints are not included in F1–F6; do not add them without scope approval. Registration does not disclose whether an email already exists beyond a generic duplicate-email response (409).
- Password: 12–128 characters; no silent trimming; reject all-whitespace. Argon2id hash only.
- `title`: 5–120 characters after trim; reject blank/control-only; preserve user spelling; normalize whitespace.
- `description`: 10–2,000 characters after trim; reject blank/control-only; normalize whitespace.
- `claim_statement`: 10–2,000 characters after trim; required; restricted from report owner; normalize whitespace.
- `decision_note`: optional 0–1,000 characters; trimmed; required for `OTHER` reason code. Claim decision notes are claimant-visible; do not put private moderator-only commentary in this field. Private moderator notes are not a v1 feature. `information_request_note nvarchar(1000)` and `information_requested_at_utc datetime2(3)` store the latest moderator request; null until requested. A request-information action increments claim `version` and `updated_at_utc` but not `status_changed_at_utc`.
- Date `occurred_on`: not later than current campus-local date + 1 day; not earlier than 10 years before current campus-local date. Backend uses configured campus timezone solely for date validation/display; store domain date as SQL `date`. No automatic matching cutoff beyond the frozen 30-day LOST↔FOUND gap.
- All string lengths count Unicode code points after normalization; frontend limits mirror backend but backend is authoritative.
- Report type/category/location are immutable after creation. Title, description, and occurred_on are editable by owner while ACTIVE; category/location/type changes require creating a new report (or moderator closure and replacement). Moderator correction may alter title, description, occurred_on, category, or location only while report is ACTIVE, with audit reason; type remains immutable.

## 3. Visibility and authorization

All normal report views require login. The report is visible to authenticated STUDENT and MODERATOR users while ACTIVE or RESOLVED, except that WITHDRAWN/CLOSED reports are visible only to reporter and moderators. Report list/detail safe fields: report ID, type, category name, location name, title, description, occurred_on, status, created/updated timestamps, reporter display name. Do not expose reporter email, account ID, session information, internal notes, or attachment storage metadata.

- Report owner: may view own report and its own report photo; may not view claimant identity, claim statement, evidence, or moderation notes before or after recovery.
- Student non-owner: may view safe report fields and report photo for ACTIVE/RESOLVED report; cannot access withdrawn/closed report or claim data.
- Claimant: may view own claim, own statement/evidence, status, decision reason/note if the note is explicitly claimant-safe. The API does not expose internal moderator notes. Claimant may see linked report safe fields and report status.
- Moderator: may view all report fields and claim details/evidence through moderation endpoints; every access to claim/evidence detail is audited.
- Claim evidence: claimant and moderator only; report owner and other students never receive it.
- Claimant identity is never included in student report detail/list or report-owner views. After recovery, no identity disclosure is added; recovery status is public to authenticated users through the report.
- Students see potential matches only for their own ACTIVE reports, and safe counterpart fields only. Match list is not a report-visibility bypass.

## 4. API route contracts

### 4.1 Health and authentication

- `GET /api/health` → `{ "status": "ok" }` when process is alive; does not disclose dependency credentials/details and does not test dependencies.
- `GET /api/health/ready` checks SQL connectivity and confirms current Alembic schema revision equals head; return `{ "status": "ready" }` with 200 or `{ "status": "not_ready" }` with 503. No schema revision or connection detail is exposed. Configure App Service health check path to `/api/health/ready`.
- `POST /api/auth/register` body `{display_name,email,password}` → 201 `{user:{user_id,display_name,email,role:"STUDENT"},csrf_token}` and sets session cookie.
- `POST /api/auth/login` body `{email,password}` → 200 same user+csrf shape and sets cookie. Generic 401 on bad email/password/inactive account.
- `POST /api/auth/logout` → 204; revokes current session and clears cookie.
- `GET /api/auth/me` → `{user:{user_id,display_name,email,role}}`; no password/hash/session fields.
- `GET /api/auth/csrf` → `{csrf_token}` for current session. Required after page reload/login; endpoint requires valid session.
- Production frontend/API must be distinct custom hostnames under the same registrable domain (e.g. `app.example.edu` and `api.example.edu`), making browser requests same-site but cross-origin. This is mandatory; do not use unrelated default Azure hostnames for production cookie auth.
- Session cookie name: `findmything_session`; random 32-byte secret encoded URL-safe base64 without padding. SQL stores SHA-256 digest as `binary(32)` unique key, never raw cookie secret. Cookie is host-only, Path `/`, Secure, HttpOnly, SameSite=Lax, no Domain attribute, and `Max-Age=43200` with matching absolute expiry. Local development may set Secure=false only under explicit local environment; production must be Secure.
- Session lifetime: 12-hour absolute expiry, no sliding extension. `last_seen_at_utc` update is throttled to at most once per 15 minutes per session. Logout, password change, user deactivation, or role change revokes all sessions for that user. If login/register arrives with an existing session cookie, revoke that current session and issue a fresh session; do not revoke other sessions belonging to the user. No persistent “remember me.”
- CSRF token: 32 random bytes, URL-safe base64 no padding; store SHA-256 digest in session row (`csrf_token_hash binary(32)`). Return raw token only from login/register/CSRF endpoint. Compare hashes constant-time. Require `X-CSRF-Token` and exact configured `Origin` on all cookie-authenticated state-changing requests (POST/PATCH/PUT/DELETE). Missing/mismatched token or origin → 403. Login/register are exempt from session CSRF but require Origin validation in browser deployments.

### 4.2 Reports

- `GET /api/reports?type=LOST|FOUND&status=ACTIVE|RESOLVED|WITHDRAWN|CLOSED&category_id=&location_id=&q=&page=&page_size=`. Student default status ACTIVE; when a student requests WITHDRAWN/CLOSED, return only their own reports; moderators may query all reports. ACTIVE/RESOLVED lists return campus reports visible to authenticated students. Stable order `created_at_utc DESC, report_id ASC`. `q` searches title and description with SQL Server parameterized contains search; no fuzzy/AI search.
- `POST /api/reports` body `{report_type,category_id,location_id,title,description,occurred_on}` → 201 report safe shape. `reporter_user_id`, status, versions, timestamps, matching metadata are server-owned. Creation defaults ACTIVE, `version=1`, `matching_version=1`.
- `GET /api/reports/{report_id}` → safe report shape plus `is_owner` and `can_claim` booleans; booleans are computed server-side.
- `PATCH /api/reports/{report_id}` body `{title?,description?,occurred_on?,expected_version}`. Owner may change allowed fields only while ACTIVE and no PENDING/VERIFIED claim references report. Moderator correction uses `POST /api/moderation/reports/{report_id}/correct` with `{title?,description?,occurred_on?,category_id?,location_id?,expected_version,decision_note?}`; server sets reason `MODERATOR_CORRECTION`. It is allowed for ACTIVE and terminal reports; report type is immutable. Each successful edit increments `version`; matching_version increments if a matching field changes. If report remains ACTIVE, invalidate matches and enqueue matching; if report is terminal, invalidate matches but do not enqueue matching or change its status.
- `POST /api/reports/{report_id}/withdraw` body `{expected_version}`; owner only; ACTIVE only; server sets reason `OWNER_WITHDRAWAL`; no PENDING/VERIFIED claims attached as FOUND or linked LOST.
- `POST /api/moderation/reports/{report_id}/close` body `{reason_code,decision_note?,expected_version}`; reason must be `INVALID_REPORT`, `DUPLICATE_REPORT`, `INAPPROPRIATE_CONTENT`, `ADMINISTRATIVE_CLOSURE`, or `OTHER`; ACTIVE only; all related PENDING/VERIFIED claims must be terminalized first.
- `POST /api/moderation/reports/{report_id}/reopen` body `{decision_note?,expected_version}`; server sets reason `MODERATOR_REOPEN`; WITHDRAWN/CLOSED only. Reopen to ACTIVE; does not reopen claims.
- Report photo flow is canonical two-step: create report first, then upload photo. `POST /api/reports/{report_id}/photo` multipart field `file`; owner only, report ACTIVE or RESOLVED; max one current photo. If one exists, request returns 409; delete first to replace. Report creation is not rolled back if upload fails. `DELETE /api/reports/{report_id}/photo` owner or moderator; 204. `GET /api/reports/{report_id}/photo` authorized stream; `Cache-Control: private, no-store`, `X-Content-Type-Options: nosniff`, safe inline filename.

### 4.3 Matching

- `GET /api/reports/{report_id}/matches?page=&page_size=`; owner or moderator. For students, return only POTENTIAL rows; moderator can inspect all states. If report is terminal, student response is empty; moderator may inspect invalidated history. Stable order score DESC, date gap ASC, location score DESC, counterpart report created timestamp ASC, counterpart UUID ASC. Return `{items:[{match_id,counterpart_report,score,factors,explanation,calculated_at_utc,algorithm_version,match_status}],page,page_size,total}`. Only POTENTIAL rows are displayed to students; moderators may inspect all states.
- `POST /api/reports/{report_id}/matches/recalculate` body `{}`; owner or moderator; report must be ACTIVE. If current-version job is PENDING/PROCESSING, return 200 with its existing `{job_id,status}`. If current-version job is SUCCEEDED/SUPERSEDED/DEAD, requeue that same idempotency-key row (reset attempt_count, lease, error, and next_attempt; set PENDING) and return 202 `{job_id,status:"PENDING"}`. If no current-version row exists, insert one and return 202. Rate limited and audited; never create duplicate rows for the same report/version/algorithm.
- `POST /api/moderation/matches/{match_id}/dismiss` body `{reason_code,decision_note?}`; moderator only; reason must be `INVALID_MATCH`, `DUPLICATE_MATCH`, or `OTHER` (OTHER requires note); POTENTIAL only → DISMISSED; 200 match shape. Dismissal persists for the current pair matching versions and algorithm version.

### 4.4 Claims and moderation

- `POST /api/reports/{found_report_id}/claims` body `{claim_statement,lost_report_id?}` → 201 `{claim}`. Claimant ID derives from session. Status PENDING, version 1.
- `GET /api/me/claims?page=&page_size=` → paginated own claims, newest first then UUID.
- `GET /api/claims/{claim_id}` claimant only; moderator uses moderation route. Claimant may upload additional evidence while PENDING/VERIFIED; no chat or claim-statement edit endpoint is included. Claim status transitions and claim record/evidence/information-request mutations increment `claim.version`; evidence upload/delete does not change `status_changed_at_utc`.
- `POST /api/claims/{claim_id}/cancel` body `{expected_version}`; claimant only; PENDING or VERIFIED → CANCELLED; server sets reason `CLAIMANT_CANCELLED`; 200 `{claim}`.
- `GET /api/moderation/claims?status=PENDING|VERIFIED|RECOVERED|REJECTED|CANCELLED&page=&page_size=` moderator only; stable order created DESC then UUID.
- `GET /api/moderation/claims/{claim_id}` moderator only; returns restricted claim fields, claim history, evidence metadata (not Blob key), related report safe fields, claimant-visible decision/information-request notes, and moderator identity/history fields. Private moderator notes are not a v1 feature.
- Successful claim verify/reject/revoke actions return `{claim}` with the updated claimant-safe Claim DTO.
- `POST /api/moderation/claims/{claim_id}/verify` body `{decision_note?,expected_version}`; server sets reason `OWNERSHIP_CONFIRMED`; PENDING → VERIFIED. Moderator cannot be claimant or FOUND report owner.
- `POST /api/moderation/claims/{claim_id}/reject` body `{reason_code,decision_note?,expected_version}`; reason must be `INSUFFICIENT_EVIDENCE`, `OWNERSHIP_NOT_CONFIRMED`, `DUPLICATE_CLAIM`, or `OTHER`; PENDING → REJECTED only.
- `POST /api/moderation/claims/{claim_id}/revoke-verification` body `{decision_note?,expected_version}`; server sets reason `VERIFICATION_REVOKED`; VERIFIED → REJECTED. The claim row `reviewed_by_user_id/reviewed_at_utc` represent the latest verification/rejection/revocation decision only; recovery does not overwrite them. Recovery actor/time are stored in `recoveries` and claim history.
- `POST /api/moderation/claims/{claim_id}/request-information` body `{decision_note,expected_version}`; PENDING only; note required (10–1,000 chars), no state transition; save as latest information-request note/time on claim, increment claim version, and record moderation activity without storing note text in audit metadata. Visible to claimant; return `{claim}`.
- `POST /api/moderation/claims/{claim_id}/recover` body `{decision_note?,expected_version}`; server sets reason `RECOVERY_CONFIRMED`; VERIFIED → RECOVERED and atomically resolves report(s), creates recovery and rejects competing PENDING claims. Return `{claim,recovery,resolved_reports:[report_id,...]}`.
- `POST /api/moderation/recoveries/{recovery_id}/void` body `{decision_note,expected_claim_version}`; server sets reason `RECOVERY_VOID`; note required; recovery void and safe claim/report reversal are one transaction. Return `{claim,recovery,reopened_reports:[report_id,...],reports_requiring_reconciliation:[report_id,...]}`.
- `POST /api/claims/{claim_id}/evidence` multipart field `files[]`; claimant only, PENDING or VERIFIED, max three total images, each ≤5 MB. If count limit exceeded return 409. `GET /api/claims/{claim_id}/evidence/{evidence_id}` claimant or moderator only; `Cache-Control: private, no-store`, `nosniff`.

### 4.5 Analytics and audit

- `GET /api/moderation/analytics/summary?from=YYYY-MM-DD&to=YYYY-MM-DD` moderator only. Dates inclusive, max range 366 days, default last 90 days through today. Return `{period:{from,to,as_of_utc},lost_reports,found_reports,active_reports,claims:{submitted,verified,rejected,cancelled},recoveries,recovery_rate_pct,recovery_rate_non_withdrawn_pct,by_category:[{category_id,name,lost,found,recoveries}],by_location:[{location_id,name,lost,found,recoveries}],monthly:[{month,lost,found,recoveries}],average_recovery_days,median_recovery_days}`. Metrics obey Blueprint cohort definitions; unavailable rate/time values are `null`, not zero.
- `GET /api/moderation/activity?page=&page_size=` moderator only; safe audit fields only, newest first. DTO: `{items:[{activity_id,event_type,target_type,target_id,actor:{user_id,display_name}|null,created_at_utc,outcome,correlation_id,metadata}],page,page_size,total}`. Metadata is sanitized/allowlisted; only moderator report-action notes may appear, never claim statement/evidence or credentials. Claim statements/evidence and secret metadata are never returned.

## 5. Canonical reason codes and audit events

### Report reason codes
`OWNER_WITHDRAWAL`, `INVALID_REPORT`, `DUPLICATE_REPORT`, `INAPPROPRIATE_CONTENT`, `ADMINISTRATIVE_CLOSURE`, `RECOVERY_COMPLETED`, `MODERATOR_CORRECTION`, `MODERATOR_REOPEN`, `RECOVERY_VOID`, `OTHER`.

### Match dismissal reason codes
`INVALID_MATCH`, `DUPLICATE_MATCH`, `OTHER` (OTHER requires a nonempty note). Only a moderator may dismiss a match.

### Claim decision reason codes
`OWNERSHIP_CONFIRMED`, `INSUFFICIENT_EVIDENCE`, `OWNERSHIP_NOT_CONFIRMED`, `DUPLICATE_CLAIM`, `OTHER_CLAIM_RECOVERED`, `CLAIMANT_CANCELLED`, `VERIFICATION_REVOKED`, `RECOVERY_CONFIRMED`, `OTHER`.

`OTHER` requires a nonempty decision note. Reason codes are stored uppercase exactly as listed. Automatic conflict rejection uses actor=null/system, reason `OTHER_CLAIM_RECOVERED`, and note `A competing claim completed recovery.` This note is claimant-safe.

### Event types
`AUTH_REGISTERED`, `AUTH_LOGIN_SUCCEEDED`, `AUTH_LOGIN_FAILED`, `AUTH_LOGOUT`, `USER_DEACTIVATED`, `REPORT_CREATED`, `REPORT_UPDATED`, `REPORT_WITHDRAWN`, `REPORT_CLOSED`, `REPORT_REOPENED`, `REPORT_MODERATOR_CORRECTED`, `REPORT_PHOTO_UPLOADED`, `REPORT_PHOTO_DELETED`, `MATCH_JOB_QUEUED`, `MATCH_JOB_SUCCEEDED`, `MATCH_JOB_FAILED`, `MATCH_DISMISSED`, `CLAIM_SUBMITTED`, `CLAIM_VERIFIED`, `CLAIM_REJECTED`, `CLAIM_VERIFICATION_REVOKED`, `CLAIM_CANCELLED`, `CLAIM_INFORMATION_REQUESTED`, `CLAIM_EVIDENCE_UPLOADED`, `CLAIM_EVIDENCE_DELETED`, `RECOVERY_COMPLETED`, `RECOVERY_VOIDED`, `MODERATOR_CLAIM_DETAIL_ACCESSED`, `MODERATOR_EVIDENCE_ACCESSED`, `RATE_LIMIT_TRIGGERED`.

Event payloads may include actor, target type/id, reason code, outcome, request_id, and allowlisted metadata. For report moderator actions only, `decision_note` (max 1,000 chars, moderator-only) may be stored in activity metadata; `OTHER` requires it. Claim decision notes are stored on claim/history and are claimant-visible; claim information-request note is stored on claim. Never log claim statement/evidence, passwords, tokens, Blob keys, original filenames, or raw user content.

## 6. SQL schema implementation decisions

- Use SQL Server `uniqueidentifier`, `datetime2(3)` UTC, `date`, `bit`, `nvarchar`, `varbinary`, `decimal`, and `int` consistently. IDs are generated in application with UUIDv4 unless a specific table requires DB-generated ID (none do).
- `users.display_name nvarchar(80)`, `email_normalized nvarchar(254)`, `password_hash nvarchar(255)`; `is_active bit NOT NULL DEFAULT 1`.
- `sessions.session_token_hash binary(32) PK`, `csrf_token_hash binary(32) NOT NULL`, user FK, created/expires/last_seen/revoked datetime2(3), optional user-agent summary nvarchar(256).
- `categories.category_id uniqueidentifier PK`, `name nvarchar(80) UNIQUE`, `is_active bit`.
- `locations.location_id uniqueidentifier PK`, `name nvarchar(120) UNIQUE`, `zone_id uniqueidentifier FK locations.location_id` (zone rows are top-level with `zone_id=NULL`); `is_active bit`; each non-zone campus location has a parent zone. Add `is_zone bit NOT NULL DEFAULT 0`; CHECK zone row has null parent, non-zone row has nonnull parent. Zone names are unique among all location names.
- `reports.title nvarchar(120)`, `description nvarchar(2000)`, `occurred_on date`, status/type varchar(16), status_reason_code varchar(40) nullable, version/matching_version int NOT NULL DEFAULT 1, timestamps datetime2(3). `report_type` immutable after insert.
- `attachments`: one report photo per report enforced by unique filtered index on report_id where attachment_type='REPORT_PHOTO' and lifecycle state not DELETED; `attachment_type varchar(20)`; blob_key nvarchar(512) unique; original_filename nvarchar(255); content_type varchar(32); size_bytes bigint; upload_status varchar(16); deleted_at_utc nullable; purge_after_utc nullable.
- `claim_evidence`: same metadata model as attachment but claim_id FK; unique blob_key; `description nvarchar(500)` nullable; deleted/purge timestamps; three active evidence images maximum enforced in transaction under claim lock.
- `matches.score/factor scores decimal(5,2)`, explanation `nvarchar(max)` JSON validated in application; SQL check `ISJSON(explanation)=1`; `invalidated_at_utc datetime2(3)` and `invalidation_reason varchar(64)` nullable; unique `(lost_report_id,found_report_id,algorithm_version)`.
- `claims.claim_statement nvarchar(2000)`, status varchar(16), version int, report versions int nullable, snapshot JSON `nvarchar(max)` with ISJSON check, reviewer fields and reason/note (reason varchar(40), note nvarchar(1000)), information request note/time nullable. Claim snapshots contain only safe report fields, not claimant private information.
- `matching_jobs`: report FK, report_matching_version int, algorithm_version varchar(16), status varchar(16), attempt_count int default 0, next_attempt_at_utc datetime2(3), lease_expires_at_utc nullable, last_error_code varchar(64) nullable, created/updated; unique `(report_id,report_matching_version,algorithm_version)`.
- `report_status_history`: old/new varchar(16), actor UUID nullable FK users, changed timestamp, reason varchar(40), correlation_id varchar(128). SQL trigger reads `SESSION_CONTEXT(N'actor_id')`, `SESSION_CONTEXT(N'reason_code')`, `SESSION_CONTEXT(N'correlation_id')`. Set all three before status change inside transaction; clear all three to NULL before transaction/connection returns to pool, including exception path.
- `claim_status_history`: old/new status, actor nullable, changed timestamp, reason varchar(40), note nvarchar(1000) nullable, correlation_id varchar(128).
- `activity_logs`: actor nullable, event_type varchar(64), target_type varchar(32), target UUID nullable, created timestamp, outcome varchar(16), correlation_id varchar(128), metadata `nvarchar(max)` ISJSON and allowlisted only. Report moderation decision note may be included; no claim statement/evidence or secret data.
- `recoveries`: claim FK (not unique), FOUND and optional LOST FK, status varchar(16), completing moderator FK users, completed timestamp, voiding moderator FK nullable, void timestamp/reason/note nullable, prior report status/version and resulting version snapshots. SQL FK constraints for both moderator columns must be present; see filtered unique indexes in §20.
- Use filtered unique indexes for active-claim uniqueness: unique claimant+FOUND where status in PENDING/VERIFIED; unique FOUND where status in VERIFIED/RECOVERED; unique nonnull LOST report where status in VERIFIED/RECOVERED. Because SQL Server filtered index predicates do not support every expression, if a filtered predicate cannot directly represent the status set, implement persisted computed guard columns (`active_found_guard`, `active_claimant_found_guard`, `active_lost_guard`) and unique filtered indexes where guard IS NOT NULL. This is mandatory rather than optional fallback.
- For report status history trigger, application must not also insert report history rows. All claim history/audit writes occur in application transaction.
- Every state-changing update uses expected `version` or conditional status predicate; mismatch returns 409. Report create/edit/status action returns `{report}`. Claim create returns `{claim}`; cancel/verify/reject/revoke/request-information return `{claim}`; evidence upload returns `{evidence}`. Status transitions increment claim/report version exactly once per transaction; claim evidence upload/delete and information-request update increment claim version exactly once but do not change claim status/status_changed_at.

## 7. Seed/reference data and campus configuration

No public category/location management or ADMIN role is added. Initial reference data is supplied via a checked-in deployment template `config/campus.example.json`, copied to untracked `config/campus.json` and loaded by idempotent seed command. Owner/deployment operator must edit it to campus values before deployment. Required schema: campus display name, IANA timezone, categories (stable slug + display name), zones (slug + display name), locations (slug + display name + zone slug). Seed IDs are deterministic UUIDv5 derived from namespace + slug; names/slugs unique. Seed creates STUDENT/MODERATOR roles, categories, zone/location rows. Seed does not create users or moderator accounts. Reference rows may be deactivated, not deleted, once used by reports. If campus config is absent or invalid, seed/deployment fails clearly; do not guess campus taxonomy.

## 8. Matching version and edit mapping

- Matching-relevant fields: `report_type`, `category_id`, `location_id`, `occurred_on`, `title`, `description`, and status eligibility (ACTIVE vs non-ACTIVE).
- Type is immutable; category/location are immutable for owner; moderator may change category/location in correction. Title/description/occurred_on are matching-relevant and editable as stated above.
- Any change to a matching-relevant field increments matching_version exactly once per report update transaction, invalidates all existing match rows involving report, and enqueues matching job in same SQL transaction if report remains ACTIVE.
- Non-matching fields (photo metadata, owner display name, audit note) do not increment matching_version.
- For a match unique key collision after versions change, update/reuse same `(LOST,FOUND,algorithm_version)` row. If previous state was DISMISSED and either report matching_version changed, reset to POTENTIAL and overwrite current calculation fields; if versions unchanged, dismissal remains. Preserve old calculation snapshot in activity log event `MATCH_JOB_SUCCEEDED` metadata with old score/factors/status/versions (no personal data).
- Match status endpoint dismisses only POTENTIAL. SUPPRESSED/INVALIDATED are system lifecycle states; no student action.

## 9. Session security, rate limiting, and storage

- Login: 5 failed attempts per normalized email per 15 minutes and 20 failed attempts per source IP per 15 minutes; after limit return 429 with `Retry-After`. Do not permanently lock account. Register: 5 attempts per IP per hour. Explicit match recalc: 5 per user per report per hour. Use SQL-backed rate-limit records (key hash, window start, count, expiry) with atomic transaction/update; no Redis. Source IP must be obtained only from trusted App Service forwarded headers configured by the host; never trust arbitrary client-supplied X-Forwarded-For.
- Uploads: re-encode accepted images to remove EXIF/metadata, normalize output to JPEG for photos unless source is transparent PNG/WebP (then output PNG/WebP preserving alpha as supported). If re-encoding fails, reject upload; do not store original unprocessed bytes. Use a maintained image library and test signature/decoder behavior.
- Blob access: App Service managed identity with least-privilege Blob Data Contributor on the dedicated container/account; do not use account keys in production. Local development may use connection string from local environment only. Blob container private, public access disabled.
- SQL access: SQLAlchemy with `pyodbc` and Microsoft ODBC Driver 18 for SQL Server. App Service deployment must provide the compatible driver. Connection string uses encryption and certificate validation; `TrustServerCertificate` must be false in production. SQL authentication may be used only if managed identity SQL auth is unavailable for the selected Azure SQL configuration; if used, secret is App Service setting/Key Vault, not repository. Prefer Azure SQL managed identity when supported by chosen App Service setup.
- Alembic migrations run as a separate deployment step/one-off command before app rollout; never automatically run migrations in every web worker startup. Startup checks schema compatibility and fails readiness if migration is pending.

## 10. Retention and cleanup

- Terminal timestamp for report attachment retention is the latest transition into a terminal state (RESOLVED/WITHDRAWN/CLOSED); for claim evidence it is latest claim transition into terminal state (RECOVERED/REJECTED/CANCELLED). Set `purge_after_utc = terminal_transition_at + 90 days`.
- Reopening report or voiding recovery before purge clears `purge_after_utc` and cancels scheduled purge. If a purge already completed, the attachment cannot be restored; reopen remains allowed but photo/evidence is absent. Never purge while entity is nonterminal.
- Cleanup command runs daily (UTC) via Azure App Service scheduled job/Function only if available under subscription; otherwise documented operator-run CLI is mandatory. Do not add a new runtime dependency. Command deletes Blob first, then marks SQL metadata deleted in transaction; Blob 404 counts as success. If Blob delete fails, keep metadata and retry next run. Orphan Blob cleanup removes objects with no SQL row older than 24 hours. Audit cleanup outcome, not filename/content.
- Audit/activity log retention 365 days. Status history, reports, claims, and recovery workflow rows are retained indefinitely for the project; attachment metadata rows are retained with `deleted_at_utc` and never hard-deleted. Purge activity_logs older than 365 days by maintenance command; retain status history.

## 11. Matching jobs and operator maintenance

- No ADMIN role or admin UI. Dead-letter (`DEAD`) matching jobs are inspected/retried by an authorized operator using backend CLI commands `matching-jobs list --status DEAD` and `matching-jobs retry <job_id>`. CLI access requires deployment operator access to App Service environment; no public API.
- Retry policy: 8 attempts maximum; exponential delay 2^attempt seconds capped at 3600 seconds plus deterministic jitter derived from job UUID (0–15%); errors are sanitized to stable code. On exhaustion mark DEAD. Explicit retry resets attempt_count=0, status=PENDING, lease/error fields, and next_attempt_at=now, with operator audit record. It reuses the same idempotency-key row.
- Worker leases are 2 minutes; claim lease with SQL conditional update. Expired PROCESSING jobs may be reclaimed. Deterministic lock ordering is UUID ascending for report and claim rows.

## 12. Analytics/dashboard boundary

Both are required: (1) lightweight in-app moderator analytics summary/dashboard powered by `/api/moderation/analytics/summary`, and (2) Power BI Desktop report using read-only SQL analytics view. The in-app dashboard provides cards, trend line, category/location tables for selected period; Power BI is the course analytics/reporting deliverable and may provide richer visuals. Metrics and cohort definitions are identical. No Power BI Service publishing assumed.

## 13. Required test baseline

- Backend: pytest + FastAPI TestClient/httpx; Azure SQL integration tests use SQL Server-compatible test database (local SQL Server container where available, otherwise test Azure SQL instance only when owner explicitly authorizes use). Do not silently substitute SQLite for tests of SQL Server trigger, filtered index, locking, or transaction behavior.
- Frontend: Vitest + React Testing Library; Playwright end-to-end tests for critical student/moderator workflows.
- CI must run lint/typecheck, unit tests, frontend tests, backend tests, and migration validation. SQL Server-specific tests may be marked integration and must be run before claiming database correctness.
- Required e2e path: register/login → create LOST and FOUND → match → submit claim → moderator verify → recover → reports resolved → analytics reflects recovery. Include authorization/role negative cases, photo upload/retrieval/privacy, recovery race, cancellation-vs-recovery, withdrawal-vs-claim submission, recovery void, CSRF/CORS, rate limiting, retention cancellation, and matching dismissal reset.

## 14. UI freedom and accessibility baseline

Agents may choose visual styling within React/Vite without owner approval, provided they do not alter workflow or privacy. Use responsive layout (mobile ≥320px, tablet, desktop), keyboard-accessible controls, visible focus, semantic labels, WCAG 2.1 AA contrast where practical, form errors tied to fields, and loading/empty/error states. No external UI SaaS or paid component dependency. No visual choice may expose restricted claim information.

## 15. Rate-limit table and environment contract

### SQL rate-limit persistence

Add `rate_limit_counters` with columns: `counter_id uniqueidentifier PK`; `key_hash binary(32) NOT NULL`; `window_start_utc datetime2(3) NOT NULL`; `window_seconds int NOT NULL`; `count int NOT NULL`; `expires_at_utc datetime2(3) NOT NULL`; UNIQUE(`key_hash`,`window_start_utc`,`window_seconds`). `key_hash` is SHA-256 of a server-generated composite key (limit name + normalized email or trusted client IP/user/report UUID); raw email/IP is not stored in this table. Increment atomically under SQL transaction/lock. Delete expired counters daily. Failed login counters must not include plaintext password or user-supplied forwarding headers.

### Required configuration names

- `APP_ENV` (`development` or `production`)
- `FRONTEND_ORIGIN` (exact scheme/host/port; one origin)
- `API_PUBLIC_ORIGIN` (exact API origin; used for origin/cookie configuration)
- `CAMPUS_CONFIG_PATH` (path to campus JSON; default `config/campus.json`)
- `DATABASE_URL` (SQLAlchemy URL for Azure SQL/SQL Server with ODBC Driver 18)
- `AZURE_STORAGE_ACCOUNT_URL` (production managed identity Blob endpoint)
- `AZURE_STORAGE_CONTAINER` (private container name)
- `SESSION_COOKIE_NAME` (must equal `findmything_session` in production)
- `LOG_LEVEL` (default INFO)
- `ARGON2_*` settings only if using documented Argon2id library defaults; no custom weakening. Package/library version is pinned in lockfile.

Secrets (if any) are supplied through App Service environment settings/Key Vault and local `.env` excluded from git. No production secret is checked into `config/campus.json`.

### App Service execution and migration

- Linux App Service startup command: `uvicorn app.main:app --host 0.0.0.0 --port 8000`; configure App Service to route to port 8000. If the hosting platform requires a platform-specific port variable, use that variable while preserving the same host/command behavior.
- Frontend build-time API base is `VITE_API_BASE_URL`, set to `https://api.<owner-domain>/api` in production and local API origin in development. Do not embed credentials.
- Frontend production build output is `dist/`; Azure Static Web Apps deploys that output. SPA fallback routes to `index.html`; `/api` requests are sent directly to API hostname (not SWA proxy) using configured base URL.
- Backend readiness endpoint is `GET /api/health`; health response includes only status. App Service readiness/deployment verification also checks SQL schema revision internally but does not return revision/secrets to public caller.
- Deployment order: provision/configure services → configure managed identity and app settings → run Alembic upgrade as one-off deployment step → verify migration revision → deploy/restart API → deploy frontend → smoke test. Do not run migrations automatically on app startup.
- Alembic migration commands: `alembic upgrade head` for deployment and `alembic downgrade <revision>` only for controlled rollback when the migration is explicitly reversible. Destructive schema rollback is not automatic.

## 16. Moderator CLI and maintenance commands

- `python -m app.cli create-moderator`: interactive prompt for display name/email/password. If normalized email exists, refuse with a clear error; never update role/password implicitly. Operator must use separate explicit `deactivate-user`/`reset-password` commands if those are implemented later. Do not add public API for these operations.
- `python -m app.cli seed-reference-data`: validates campus config and upserts role/category/zone/location seed records by deterministic UUID; existing report-linked categories/locations are never renamed or deleted automatically. A name/zone change requires a reviewed config migration.
- `python -m app.cli cleanup-retention`: runs attachment and audit retention cleanup; idempotent.
- `python -m app.cli matching-jobs list --status DEAD` and `python -m app.cli matching-jobs retry <job_id>`: operator maintenance; CLI logs actor as `OPERATOR` (actor_user_id NULL) with safe target metadata and timestamp.
- Operator CLI actions must not bypass report/claim state transitions or directly edit statuses. Any CLI action that changes user activation or credentials is outside F1–F6 unless separately approved.

## 17. Canonical API resource shapes

These are API DTOs, not ORM serialization. Omit keys explicitly marked conditional; never return database-only fields, Blob keys, token hashes, password hashes, or SQL metadata.

### Report DTO

```json
{
  "report_id": "uuid",
  "report_type": "LOST|FOUND",
  "category": {"category_id": "uuid", "name": "string"},
  "location": {"location_id": "uuid", "name": "string", "zone_name": "string"},
  "title": "string",
  "description": "string",
  "occurred_on": "YYYY-MM-DD",
  "status": "ACTIVE|RESOLVED|WITHDRAWN|CLOSED",
  "reporter": {"display_name": "string"},
  "created_at_utc": "ISO-8601 UTC",
  "updated_at_utc": "ISO-8601 UTC",
  "status_changed_at_utc": "ISO-8601 UTC",
  "version": 1,
  "has_photo": false,
  "is_owner": false,
  "can_claim": false
}
```

`is_owner` and `can_claim` are included only in authenticated report detail, not list DTO. `can_claim=true` only when actor is STUDENT, report is ACTIVE FOUND, actor is not owner, no VERIFIED/RECOVERED claim blocks the FOUND report, and actor has no PENDING/VERIFIED claim on that FOUND report. Report list DTO omits these booleans. Report owner detail also includes `claim_activity:{has_active_claim:boolean}`, true iff at least one PENDING or VERIFIED claim references the report as FOUND or linked LOST; it reveals no claimant, count, statement, evidence, or decision details. Non-owners never receive this field. Reporter email/user ID and `matching_version` are never returned. `status_reason_code` is shown to moderator only; student report DTO omits it.

### Claim DTO (claimant view)

```json
{
  "claim_id": "uuid",
  "found_report_id": "uuid",
  "lost_report_id": "uuid|null",
  "claim_statement": "string",
  "status": "PENDING|VERIFIED|RECOVERED|REJECTED|CANCELLED",
  "version": 1,
  "created_at_utc": "ISO-8601 UTC",
  "updated_at_utc": "ISO-8601 UTC",
  "status_changed_at_utc": "ISO-8601 UTC",
  "decision": {"reason_code": "string|null", "decision_note": "string|null", "reviewed_at_utc": "ISO-8601 UTC|null"},
  "information_request": {"note": "string|null", "requested_at_utc": "ISO-8601 UTC|null"},
  "evidence": [{"evidence_id": "uuid", "content_type": "string", "size_bytes": 0, "uploaded_at_utc": "ISO-8601 UTC"}],
  "found_report": {"report_id": "uuid", "title": "string", "status": "string"},
  "lost_report": {"report_id": "uuid", "title": "string", "status": "string"}|null
}
```

Claimant DTO never includes `reviewed_by_user_id`, moderator identity, internal notes, Blob keys, or another claimant's information. `claim_statement` is returned only to the claimant and moderator.

### Claim DTO (moderator view)

Moderator claim detail adds `claimant:{user_id,display_name,email}`, `reviewer:{user_id,display_name}|null`, `decision_note` (same claimant-visible note), complete status history `{old_status,new_status,actor_display_name|null,reason_code,note,changed_at_utc}`, and related report DTOs. Evidence list still excludes Blob key; evidence content is retrieved only through its authorized stream endpoint. Moderator detail GET is audited.

### Match DTO

```json
{
  "match_id": "uuid",
  "counterpart_report": {"report_id":"uuid","report_type":"LOST|FOUND","title":"string","category_name":"string","location_name":"string","occurred_on":"YYYY-MM-DD","status":"ACTIVE"},
  "score": 0.0,
  "factors": {"category":0.0,"location":0.0,"date":0.0,"keywords":0.0},
  "explanation": {"category":"string","location":"string","date":"string","keywords":"string"},
  "calculated_at_utc":"ISO-8601 UTC",
  "algorithm_version":"match-v1",
  "match_status":"POTENTIAL|SUPPRESSED|INVALIDATED|DISMISSED"
}
```

Explanation strings are deterministic human-readable summaries generated from score factors, not freeform AI output. Counterpart report fields are safe display fields only.

### Attachment upload response

Upload returns `{attachment:{attachment_id,content_type,size_bytes,created_at_utc}}` or for claim evidence `{evidence:{evidence_id,content_type,size_bytes,uploaded_at_utc}}`. Never return Blob key, SAS URL, storage account/container, or permanent URL.

### Exact upload size

The maximum upload body size is **5,000,000 bytes (decimal MB)** per image, including report photo and each claim evidence photo. The limit is enforced server-side before Blob upload and again against decoded/re-encoded output. Three claim evidence images are allowed total, not three per request. The report allows one current photo total.

### Claim evidence deletion

`DELETE /api/claims/{claim_id}/evidence/{evidence_id}` is allowed to claimant only while claim is PENDING or VERIFIED, and to moderator with a reason via `DELETE /api/moderation/claims/{claim_id}/evidence/{evidence_id}` body `{reason_code,decision_note?}`. Moderator reason code must be `OTHER` or `INSUFFICIENT_EVIDENCE`; `OTHER` requires note. Both return 204 and mark metadata deleted after Blob deletion succeeds (Blob 404 is success). If Blob deletion fails, return 503 and retain active metadata for retry; do not claim deletion succeeded.

## 18. Claim verification and recovery preconditions (operational)

At verification time, lock/recheck the claim, FOUND report, optional LOST report, and any competing VERIFIED claim rows. Claim must be PENDING; FOUND and optional LOST must still be ACTIVE; optional LOST must still be owned by claimant; moderator must not be claimant or FOUND report owner; no VERIFIED claim may conflict with either FOUND or linked LOST. A conflict returns 409 and leaves state unchanged.

At recovery time, the claim must be VERIFIED and reports must be ACTIVE; the moderator cannot be claimant or FOUND report owner. Lock all relevant reports and claim rows in UUID ascending order. Recovery does not overwrite the claim’s latest verification reviewer fields; completing moderator/time are recorded in the recovery row and claim status history. System rejection of competing claims writes status history with actor NULL and reason `OTHER_CLAIM_RECOVERED`, note as defined in §5, and activity event with system outcome. Recovery race losers receive 409; no partial state change is allowed.

## 19. API list endpoint order and allowed page filters

- Reports: `created_at_utc DESC, report_id ASC`.
- Own claims and moderator claims: `created_at_utc DESC, claim_id ASC`.
- Activity: `created_at_utc DESC, activity_id ASC`.
- Matches: ranking order from frozen match-v1 ranking; match list ordering does not override the score tie-break rules.
- Category/location analytics arrays: display name ascending, then UUID ascending.
- Monthly analytics: month ascending.
- Query parameters with unknown filter names return 422. Empty result is 200 with `items=[]`, `total=0`; page beyond last page is 200 with empty items.


## 20. Complete SQL table columns and constraints

This section supplements the logical entities in Blueprint §3.2. All tables use the types/defaults below; columns not marked nullable are `NOT NULL`. All UTC timestamps are `datetime2(3)` and app-generated timestamps use UTC. UUID PKs are application-generated UUIDv4 except seeded roles/categories/locations (UUIDv5 as §7).

| Table | Required columns | Nullable/constraints |
|---|---|---|
| `roles` | `role_id uniqueidentifier PK`, `name varchar(16) UNIQUE`, `description nvarchar(200)` | description nullable; values only STUDENT/MODERATOR |
| `users` | `user_id uniqueidentifier PK`, `role_id uniqueidentifier FK roles`, `display_name nvarchar(80)`, `email_normalized nvarchar(254) UNIQUE`, `password_hash nvarchar(255)`, `is_active bit DEFAULT 1`, `created_at_utc`, `updated_at_utc` | no nullable fields |
| `sessions` | `session_token_hash binary(32) PK`, `user_id uniqueidentifier FK users`, `csrf_token_hash binary(32)`, `created_at_utc`, `expires_at_utc`, `last_seen_at_utc` | `revoked_at_utc datetime2(3)` nullable; `user_agent_summary nvarchar(256)` nullable |
| `categories` | `category_id uniqueidentifier PK`, `slug varchar(64) UNIQUE`, `name nvarchar(80) UNIQUE`, `is_active bit DEFAULT 1` | none |
| `locations` | `location_id uniqueidentifier PK`, `slug varchar(64) UNIQUE`, `name nvarchar(120) UNIQUE`, `is_zone bit DEFAULT 0`, `zone_id uniqueidentifier FK locations`, `is_active bit DEFAULT 1` | zone rows have `zone_id=NULL`; non-zone rows require zone_id pointing to is_zone=1 |
| `reports` | `report_id uniqueidentifier PK`, `reporter_user_id uniqueidentifier FK users`, `report_type varchar(8)`, `category_id FK categories`, `location_id FK locations`, `title nvarchar(120)`, `description nvarchar(2000)`, `occurred_on date`, `status varchar(16)`, `status_changed_at_utc`, `created_at_utc`, `updated_at_utc`, `version int DEFAULT 1`, `matching_version int DEFAULT 1` | `status_reason_code varchar(40)` nullable; report_type LOST/FOUND; status ACTIVE/RESOLVED/WITHDRAWN/CLOSED; version and matching_version ≥1 |
| `attachments` | `attachment_id uniqueidentifier PK`, `report_id FK reports`, `uploaded_by_user_id FK users`, `attachment_type varchar(20)`, `blob_key nvarchar(512) UNIQUE`, `original_filename nvarchar(255)`, `content_type varchar(32)`, `size_bytes bigint`, `upload_status varchar(16)`, `created_at_utc` | `deleted_at_utc`, `purge_after_utc` nullable; attachment_type REPORT_PHOTO; upload_status ACTIVE/DELETED/PENDING_CLEANUP; size 1..5,000,000 |
| `matches` | `match_id uniqueidentifier PK`, `lost_report_id FK reports`, `found_report_id FK reports`, `score decimal(5,2)`, four factor columns `decimal(5,2)`, `explanation nvarchar(max)`, `algorithm_version varchar(16)`, `calculated_at_utc`, `lost_report_matching_version int`, `found_report_matching_version int`, `match_status varchar(16)` | invalidated timestamp/reason nullable; ISJSON(explanation)=1; score/factors 0..100; unique LOST+FOUND+algorithm; pair IDs differ |
| `claims` | `claim_id uniqueidentifier PK`, `found_report_id FK reports`, `claimant_user_id FK users`, `claim_statement nvarchar(2000)`, `status varchar(16)`, `version int DEFAULT 1`, `created_at_utc`, `updated_at_utc`, `status_changed_at_utc` | `lost_report_id FK reports` nullable; FOUND report version at submission required; linked LOST report version nullable; compact report snapshot JSON `nvarchar(max)` required/ISJSON; reviewer ID FK users nullable; reviewed timestamp nullable; reason varchar(40) nullable; note nvarchar(1000) nullable; status in fixed five values; version≥1 |
| `matching_jobs` | `job_id uniqueidentifier PK`, `report_id FK reports`, `report_matching_version int`, `algorithm_version varchar(16)`, `status varchar(16)`, `attempt_count int DEFAULT 0`, `created_at_utc`, `updated_at_utc` | next_attempt timestamp required for PENDING; lease nullable; error code varchar(64) nullable; unique report+version+algorithm; status fixed five values |
| `report_status_history` | `history_id uniqueidentifier PK`, `report_id FK reports`, `old_status varchar(16)`, `new_status varchar(16)`, `changed_at_utc`, `reason_code varchar(40)`, `correlation_id varchar(128)` | actor FK users nullable (system) |
| `claim_status_history` | `history_id uniqueidentifier PK`, `claim_id FK claims`, `old_status varchar(16)`, `new_status varchar(16)`, `changed_at_utc`, `reason_code varchar(40)`, `correlation_id varchar(128)` | actor FK users nullable; note nvarchar(1000) nullable |
| `activity_logs` | `activity_id uniqueidentifier PK`, `event_type varchar(64)`, `target_type varchar(32)`, `created_at_utc`, `outcome varchar(16)`, `correlation_id varchar(128)` | actor FK users nullable; target UUID nullable; metadata nvarchar(max) nullable/ISJSON if present |
| `recoveries` | `recovery_id uniqueidentifier PK`, `claim_id FK claims`, `found_report_id FK reports`, `status varchar(16)`, `completed_by_moderator_id FK users`, `completed_at_utc` | linked LOST FK nullable; voiding moderator FK nullable; void timestamp/reason/note nullable; prior report statuses/versions and post-recovery versions stored as explicit columns; status COMPLETED/VOIDED |
| `claim_evidence` | `evidence_id uniqueidentifier PK`, `claim_id FK claims`, `uploaded_by_user_id FK users`, `blob_key nvarchar(512) UNIQUE`, `original_filename nvarchar(255)`, `content_type varchar(32)`, `size_bytes bigint`, `upload_status varchar(16)`, `uploaded_at_utc` | description nvarchar(500) nullable; deleted/purge timestamps nullable; upload_status ACTIVE/DELETED/PENDING_CLEANUP; size 1..5,000,000 |
| `rate_limit_counters` | `counter_id uniqueidentifier PK`, `key_hash binary(32)`, `window_start_utc`, `window_seconds int`, `count int`, `expires_at_utc` | unique key_hash+window_start+window_seconds; count≥0; window_seconds>0 |

### Recovery provenance columns

`recoveries` may contain multiple attempts for a claim. Voided recovery rows are immutable history; a later successful recovery creates a new row. Add a filtered unique index on `claim_id WHERE status='COMPLETED'`, and filtered unique indexes on `found_report_id WHERE status='COMPLETED'` and nonnull `lost_report_id WHERE status='COMPLETED'`. These enforce at most one currently completed recovery per claim/FOUND/LOST while allowing a voided attempt followed by a new recovery. `recoveries` stores prior status and version for each affected report: `found_prior_status varchar(16)`, `found_prior_version int`, `found_post_version int`, and, when linked LOST exists, `lost_prior_status varchar(16)`, `lost_prior_version int`, `lost_post_version int`. These are nullable only for the linked LOST report fields. Recovery void reopens a report only if its current status and version equal the saved post-recovery status/version; otherwise that report remains unchanged and requires moderator reconciliation.

### Additional required indexes/constraints

- FK constraints must be created for every FK listed above, including both recovery moderator IDs and report/claim evidence uploader IDs.
- `reports` CHECK `version>=1 AND matching_version>=1`; `claims` CHECK `version>=1`; `matching_jobs` CHECK `attempt_count>=0`.
- `locations` self-FK plus service validation enforce zone parent type; SQL CHECK alone cannot inspect parent row.
- Report status trigger writes only on actual status change (old status differs from new).
- Attachments/evidence are soft-deleted. Their active unique/count constraints apply only when `deleted_at_utc IS NULL` and `upload_status='ACTIVE'`.
- Add index `reports(status, report_type, created_at_utc)`, `claims(status, created_at_utc)`, `claim_evidence(claim_id, uploaded_at_utc)`, `attachments(report_id, created_at_utc)`, and rate-limit expiry index.

## 21. Remaining operational constants

- CORS: allow only `FRONTEND_ORIGIN`; credentials enabled; allowed request headers are `Content-Type`, `X-CSRF-Token`, and `X-Request-ID`; allowed methods are GET, POST, PATCH, PUT, DELETE, OPTIONS. Never wildcard origins/headers with credentials. Respond to preflight with the exact configured origin and `Vary: Origin`.
- Blob key format: `attachments/<uuidv4>.<validated-extension>`; no report title, claimant name, email, original filename, or client-provided key appears in the key. Report photos and claim evidence share the private container but are distinguished by SQL metadata and authorization.
- Image processing uses Pillow (Python) pinned in the backend lockfile. Decode, normalize EXIF orientation into pixels, remove EXIF/metadata, and re-encode to the same allowed source format (JPEG→JPEG, PNG→PNG, WebP→WebP), preserving transparency where applicable. Reject decoder errors, animated formats, and files with output size over 5,000,000 bytes. MIME and extension are derived from validated decoded format, not trusted from request headers.
- Matching candidate generation has no arbitrary candidate-count cap. Process all eligible candidates under `match-v1`; do not truncate by recency, score prefilter, or SQL row limit.
- Matching `attempt_count` starts at 0 and increments after each failed attempt. After failure number N (N=1..7), delay is `min(2^N, 3600)` seconds plus deterministic UUID-derived jitter from 0 to 15% of that delay. After the eighth failed attempt, mark DEAD; do not schedule a ninth automatic attempt. Explicit operator retry resets count to 0.
- `WEBSITES_PORT=8000` is configured for Linux App Service when using the frozen Uvicorn startup command. If App Service platform configuration differs, preserve application listening behavior and validate through deployment smoke test; do not replace FastAPI/Uvicorn.

## 22. Analytics metric semantics

For API analytics period `[from,to]`:

- `lost_reports` / `found_reports`: count reports of that type whose `created_at_utc` campus-local date is in the inclusive cohort range.
- `active_reports`: count reports created in the cohort range whose current status is ACTIVE at `as_of_utc`.
- `claims.submitted`: claims created in the period.
- `claims.verified`, `claims.rejected`, `claims.cancelled`: claim status transitions into the respective state during the period (use `claim_status_history.changed_at_utc`; count transition events, not current status totals).
- `recoveries`: completed recovery records whose `completed_at_utc` falls in the selected period and are not currently VOIDED.
- Main recovery rate: count FOUND reports created in cohort range that have a non-voided completed recovery by `as_of_utc` divided by all FOUND reports created in that range. WITHDRAWN and CLOSED remain denominator.
- Secondary rate: same numerator divided by cohort FOUND reports whose current status is not WITHDRAWN. CLOSED remains in this secondary denominator. Return null if denominator is zero.
- `by_category` / `by_location`: LOST/FOUND report counts by report creation cohort and recovery count for FOUND reports in that cohort with completed non-voided recovery by `as_of_utc`.
- `monthly`: group LOST/FOUND reports by report-created month; monthly recoveries are recoveries of FOUND reports created in that same month, not recovery-event month. Recovery-event month counts are available separately through `recoveries`/Power BI view.
- Average/median recovery days: elapsed UTC days from FOUND report `created_at_utc` to non-voided recovery `completed_at_utc` for recovered FOUND reports whose creation date is in selected cohort range. Round to one decimal place. Null if no qualifying recoveries.
- All date boundaries use the configured campus timezone for date selection and are converted to UTC instants for SQL filtering. The API includes `as_of_utc` to make the snapshot interpretable.

## 23. Concrete dependency choices (within the frozen stack)

The following libraries are selected; exact patch versions are pinned in backend/frontend lockfiles at implementation time and CI uses those lockfiles:

- Backend: `fastapi`, `uvicorn[standard]`, `pydantic`, `sqlalchemy`, `alembic`, `pyodbc`, `argon2-cffi` (Argon2id), `azure-identity`, `azure-storage-blob`, `Pillow`, `pytest`, `httpx`.
- Frontend: `react`, `react-dom`, `typescript`, `vite`, `vitest`, `@testing-library/react`, `@testing-library/user-event`, `@testing-library/jest-dom`, `playwright`.
- No Redis/cache server, broker, email provider, external auth provider, external UI SaaS, or paid hosted testing service.

### SQL connection implementation

Use SQLAlchemy `mssql+pyodbc` with Microsoft ODBC Driver 18. Build the SQLAlchemy URL from `DATABASE_URL` with URL-encoded ODBC parameters. Production ODBC settings must include `Encrypt=yes;TrustServerCertificate=no`. For Azure SQL managed identity, use ODBC `Authentication=ActiveDirectoryMsi` and the App Service system-assigned managed identity; grant that identity the minimum database role needed by the app. If managed identity is unavailable for the selected authorized Azure setup, use SQL authentication from protected App Service settings as the explicitly allowed fallback. Local development may use SQL authentication or Azure CLI identity but must never commit credentials.

### Blob client implementation

Use `azure-storage-blob` with `azure-identity` `DefaultAzureCredential`. Production App Service uses system-assigned managed identity; local development uses Azure CLI identity. The application uploads/downloads/deletes through SDK calls; frontend never uses Azure SDK or Blob credentials.

## 24. SQL lock ordering and workflow transaction rules

Use SQL Server row locks (`UPDLOCK, HOLDLOCK`) for eligibility checks and conditional state updates. Lock order is mandatory across every workflow:

1. All involved report rows in ascending `report_id` UUID order.
2. All involved claim rows in ascending `claim_id` UUID order.
3. All involved recovery rows in ascending `recovery_id` UUID order.
4. Write status history, activity log, and matching-job outbox records in the same transaction as the owning domain mutation.

Never acquire a claim lock before an involved report lock in claim/report workflow transactions. Matching worker first leases a job in a short transaction and commits; it must not hold a matching-job row lock while acquiring report locks. After calculation it writes match results/job outcome in a separate transaction. This avoids inversion with report update transactions that insert/requeue jobs.

- Claim submit: lock FOUND and optional LOST report rows sorted; validate ACTIVE/ownership/self-claim/verification winner; insert claim; activity log; commit.
- Claim verify/reject/revoke/cancel: lock associated FOUND and optional LOST reports sorted, then claim row; recheck state/version and conflict-of-interest; conditional update; claim history and audit; commit.
- Report edit/withdraw/close/reopen/correct: lock report first, then associated claims sorted if policy requires; conditional update/version; trigger writes report history for status transition; activity/match invalidation/outbox as appropriate; commit.
- Recovery complete: lock all involved reports sorted, then selected/competing claims sorted, then create recovery row; transition claim/report states, reject conflicting PENDING claims, insert claim history/audit and matching invalidations in one transaction; commit.
- Recovery void: lock reports sorted, then claim, then recovery row; check recovery is COMPLETED and claim RECOVERED; mark recovery VOIDED, claim RECOVERED→VERIFIED, and conditionally reopen report(s) only if status/version equals recovery post-state. Insert histories/audit in same transaction; commit.
- Cancellation-vs-recovery and report-withdrawal-vs-claim-submission races resolve by lock + conditional state/version check. The losing request receives 409 and performs no partial writes.

Blob operations cannot participate in SQL transactions. Upload uses Blob-first then SQL metadata insert with compensating Blob deletion on SQL failure. Delete uses Blob deletion first (404 success), then SQL soft-delete metadata; if Blob delete fails, do not mark metadata deleted and return 503. Cleanup retries are idempotent.

## 25. Azure identity and SQL principal boundaries

- App Service runtime managed identity is mapped to a dedicated Azure SQL database user and custom role `findmything_app_role`. Grant SELECT/INSERT/UPDATE/DELETE only on operational tables needed by the API and SELECT on the analytics view; do not grant DDL/schema-owner privileges to the runtime identity. The API does not hard-delete workflow/audit rows.
- Migration execution uses a separate deployment identity/credential with schema-change permissions. It is used only for the one-off Alembic migration step and is not configured as the long-running web app database principal.
- Power BI Desktop uses a separate read-only database principal with SELECT permission only on the approved analytics view(s). It has no access to claim statements, claimant identity, evidence metadata, moderator notes, session table, or audit payloads containing personal data.
- Azure Blob production identity has only Blob Data Contributor access scoped to the application container/account required for FindMyThing; public access remains disabled.
- Runtime identities never receive subscription-wide Owner/Contributor roles for application operation. Deployment operator privileges are separate from app runtime privileges.

## 26. SQL Server filtered-index guard columns

Implement the claim uniqueness constraints with persisted computed columns (SQL Server filtered-index predicate limitations must not weaken these invariants):

- `active_claimant_found_guard binary(32) PERSISTED = CASE WHEN status IN ('PENDING','VERIFIED') THEN CONVERT(binary(16),claimant_user_id) + CONVERT(binary(16),found_report_id) ELSE NULL END`; unique filtered index where guard IS NOT NULL.
- `active_found_guard uniqueidentifier PERSISTED = CASE WHEN status IN ('VERIFIED','RECOVERED') THEN found_report_id ELSE NULL END`; unique filtered index where guard IS NOT NULL.
- `active_lost_guard uniqueidentifier PERSISTED = CASE WHEN status IN ('VERIFIED','RECOVERED') AND lost_report_id IS NOT NULL THEN lost_report_id ELSE NULL END`; unique filtered index where guard IS NOT NULL.
- `recoveries` unique filtered indexes on `claim_id`, `found_report_id`, and nonnull `lost_report_id` where `status='COMPLETED'`.
- `attachments` unique filtered index on `report_id` where `attachment_type='REPORT_PHOTO' AND upload_status='ACTIVE' AND deleted_at_utc IS NULL`.

Do not rely solely on application-level checks for these uniqueness invariants. SQL uniqueness plus transaction locking is required.
