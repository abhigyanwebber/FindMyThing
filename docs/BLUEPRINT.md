# Blueprint — FindMyThing

**Status:** Frozen v1.0 — owner-directed design freeze  
**Purpose:** Complete implementation-level specification derived from the project research, selected stack, course alignment, and revised Architecture.  
**Implementation authorization:** Documentation is frozen. Implementation remains not started and requires a separate explicit owner instruction.

> This document describes the complete agreed project scope—not a reduced MVP. It is intended to remove implementation guesswork. All previously open design decisions within the agreed F1–F6 scope have been resolved in this freeze. Azure subscription quota/cost and service availability remain deployment-time verification items, not software-design blockers.

## 0. Governing sources and precedence

1. Latest explicit owner instruction.
2. `DECISIONS.md` for frozen project-level decisions and scope.
3. `IMPLEMENTATION_CONTRACTS.md` for detailed API/schema/security/validation/operations contracts (unless it conflicts with a higher-level frozen decision).
4. This Blueprint for workflow and requirements not superseded by the implementation contract.
5. `TECH_STACK.md` for technology choices and `ARCHITECTURE.md` for component boundaries.
6. Technical research report (reference and rationale; non-normative).
7. Coding-agent interpretation (lowest precedence).

If documents conflict, follow the precedence above and report the conflict rather than silently changing behavior.

### Course design intent

- **System Design:** modular boundaries, contracts, component interaction, consistency, failure handling, trade-offs.
- **DBMS/RDBMS:** normalized relational design, PK/FK/check/unique constraints, transactions, indexes, views, triggers, joins.
- **Azure/cloud/AZ-900:** managed services, deployment, cost, identity, shared responsibility, configuration.
- **DP-900:** SQL relational operational data, Blob object storage, analytics/read model.
- **Security/networking:** HTTPS, cookies, CSRF, CORS, authorization, private files, firewall and secrets.
- **Web Development:** React-to-REST integration, validation, loading/error states.
- **AI-900:** explain why transparent deterministic matching is chosen; do not introduce ML.
- **Design Thinking:** student and moderator flows, understandable statuses, feedback and usability.

---

# 1. Product and implementation boundary

## 1.1 Product

FindMyThing is a secure campus lost-and-found and item recovery platform.

Roles:
- Student
- Moderator

Core complete project capabilities:
- Authentication and role-based access
- Lost/found reporting and browsing
- Item photographs
- Deterministic potential matching with persisted match records
- Claim submission
- Moderator verification/rejection and recovery
- Activity/audit history
- Analytics dashboard and Power BI Desktop reporting

No unrelated features are to be introduced. The project does not include AI matching, chat, notifications, native mobile app, microservices, Kubernetes, Kafka, Redis, payments, or vector databases unless owner-approved scope changes.

## 1.2 Implementation principles

- Backend is authoritative for security and business rules.
- Azure SQL is authoritative for structured data and workflow state.
- Blob Storage is authoritative for photo bytes; SQL stores object metadata/key.
- Frontend never accesses SQL or Blob using account credentials.
- All protected operations enforce permissions on the backend.
- Every state-changing business operation records relevant audit/history data.
- Match scores suggest review priority; they do not prove ownership.
- Avoid distributed infrastructure and unnecessary abstractions.
- Database migrations, tests, and seed data are maintained with source.

---

# 2. Repository and code organization

## 2.1 Proposed repository layout

```text
FindMyThing/
  frontend/
    src/
      app/
      components/
      features/
        auth/
        reports/
        matches/
        claims/
        moderation/
        analytics/
      api/
      hooks/
      types/
      styles/
  backend/
    app/
      main.py
      api/
        router.py
        dependencies.py
        errors.py
      core/
        config.py
        security.py
        sessions.py
        logging.py
      modules/
        auth/
        users/
        reports/
        matching/
        claims/
        attachments/
        audit/
        analytics/
      persistence/
        database.py
        models/
        repositories/
      schemas/
      services/
    migrations/
    tests/
  docs/
  scripts/
  .env.example
  README.md
```

This is a logical structure; agents may refine filenames only while preserving module responsibilities and dependency direction.

## 2.2 Dependency direction

- API routes depend on application/domain services.
- Domain/application services depend on repositories/interfaces, not HTTP request objects.
- Repositories depend on SQLAlchemy/database session.
- Modules may call other modules through explicit service interfaces.
- Avoid circular imports and cross-module direct table manipulation.
- Frontend feature modules call the shared API client; they do not call one another's backend internals.

## 2.3 Layer responsibilities

| Layer | Responsibilities |
|---|---|
| API/router | HTTP status, request parsing, auth dependencies, response schema |
| Service/use case | Business rules, workflow orchestration, transaction boundaries |
| Domain | State transitions, matching calculations, invariant checks |
| Repository | SQL queries and persistence |
| Integration adapter | Blob Storage operations |
| Frontend | Rendering, form state, UX validation, API invocation |

---

# 3. Database design

## 3.1 DBMS design rules

- Target Third Normal Form where practical.
- Do not store derivable data unless required for performance/audit.
- Use PK/FK constraints and NOT NULL/CHECK/UNIQUE constraints for enforceable invariants.
- Use explicit transactions for multi-record state changes.
- Store timestamps in UTC; convert to local display time in UI.
- Use SQL Server/Azure SQL compatible types and syntax.
- Migrations are the only approved schema-change path.
- Avoid hard deletes for operational reports/claims/audit history; use lifecycle/status and retention rules.
- Never store passwords in plaintext.
- Never store Blob bytes in SQL.

## 3.2 Proposed entities

The research identifies these core entities: roles, users, categories, locations, reports, attachments, matches, claims, status history, and activity logs. Server-side sessions are required by the selected authentication architecture. Additional entities may be used only when they represent a genuine domain concept.

### roles
- `role_id` PK
- `name` UNIQUE, e.g. STUDENT, MODERATOR
- `description` nullable

### users
- `user_id` PK (UUID or SQL Server uniqueidentifier)
- `role_id` FK → roles
- `display_name`
- `email_normalized` UNIQUE
- `password_hash`
- `is_active`
- `created_at_utc`
- `updated_at_utc`

### sessions
- `session_token_hash` PK (`binary(32)`, SHA-256 digest of opaque cookie token; raw token is never persisted)
- `user_id` FK → users
- `created_at_utc`
- `expires_at_utc`
- `last_seen_at_utc`
- `revoked_at_utc` nullable
- `user_agent_summary` nullable; avoid unnecessary fingerprinting
- `csrf_token_hash` (`binary(32)`, SHA-256 digest of per-session CSRF token; required)

### categories
- `category_id` PK
- `slug` UNIQUE (stable configuration key)
- `name` UNIQUE
- `is_active`

### locations
- `location_id` PK
- `slug` UNIQUE (stable configuration key)
- `name` UNIQUE
- `is_zone` boolean
- `zone_id` self-FK nullable for zone rows; non-zone locations require a parent zone (used by `match-v1` same-zone location scoring)
- `is_active`
- campus-only location taxonomy; no GPS/distance calculation

### reports
- `report_id` PK
- `reporter_user_id` FK → users
- `report_type` CHECK in LOST, FOUND
- `category_id` FK → categories
- `location_id` FK → locations
- `title`
- `description`
- `occurred_on` DATE (the reported lost/found event date; separate from creation time)
- `status` CHECK in ACTIVE, RESOLVED, WITHDRAWN, CLOSED
- `status_changed_at_utc`
- `status_reason_code` nullable; required for CLOSED, WITHDRAWN, RESOLVED, and moderator reopen/correction as applicable
- `created_at_utc`, `updated_at_utc`
- `version` integer incremented for every persisted report edit or lifecycle transition
- `matching_version` integer incremented when matching-relevant fields or match eligibility change
- optional moderator correction metadata belongs in audit/history, not user-editable report fields

### attachments
- `attachment_id` PK
- `report_id` FK → reports
- `uploaded_by_user_id` FK → users
- `blob_key` UNIQUE
- `original_filename` sanitized display metadata only
- `content_type`
- `size_bytes`
- `created_at_utc`
- `upload_status` for coordinated SQL/Blob lifecycle
- do not store SAS URL or account key

### matches
- `match_id` PK
- `lost_report_id` FK → reports
- `found_report_id` FK → reports
- `score` DECIMAL bounded 0–100
- `category_score`, `location_score`, `date_score`, `keyword_score` DECIMAL bounded 0–100
- `explanation` short structured JSON snapshot
- `algorithm_version`, `calculated_at_utc`
- `lost_report_matching_version`, `found_report_matching_version`
- `match_status` CHECK in POTENTIAL, SUPPRESSED, INVALIDATED, DISMISSED
- `invalidated_at_utc`, `invalidation_reason` nullable
- UNIQUE(lost_report_id, found_report_id, algorithm_version)

**Canonical orientation:** every match record stores LOST report ID in `lost_report_id` and FOUND report ID in `found_report_id`, regardless of which report triggered matching.

### claims
- `claim_id` PK
- `found_report_id` FK → reports (must be FOUND)
- `claimant_user_id` FK → users
- `lost_report_id` FK → reports nullable (must be LOST and owned by claimant when supplied)
- `claim_statement` sensitive/restricted
- `status` CHECK in PENDING, VERIFIED, RECOVERED, REJECTED, CANCELLED
- `version` integer for optimistic concurrency
- `found_report_version_at_submission` required; `lost_report_version_at_submission` nullable
- compact report snapshot (selected safe fields and versions) at submission, required
- `created_at_utc`, `updated_at_utc`, `status_changed_at_utc`
- `reviewed_by_user_id`, `reviewed_at_utc`, `decision_reason_code`, `decision_note` nullable
- report snapshots are evidence context, not a second mutable report

### matching_jobs
- `job_id` PK
- `report_id` FK → reports
- `report_matching_version`, `algorithm_version`
- `status` CHECK in PENDING, PROCESSING, SUCCEEDED, SUPERSEDED, DEAD
- `attempt_count`, `next_attempt_at_utc`, `lease_expires_at_utc` nullable
- `last_error_code` sanitized nullable
- `created_at_utc`, `updated_at_utc`
- idempotency key on report ID + matching version + algorithm version

### report_status_history
- `history_id` PK
- `report_id` FK → reports
- `old_status`, `new_status`
- `changed_by_user_id` FK → users nullable for system action
- `changed_at_utc`, `reason_code`, `correlation_id`
- populated by a narrow SQL Server status-history trigger for report status updates; application writes actor/reason context to a transaction-scoped context mechanism before transition

### claim_status_history
- `history_id` PK
- `claim_id` FK → claims
- `old_status`, `new_status`
- `changed_by_user_id` FK → users nullable
- `changed_at_utc`, `reason_code`, `correlation_id`
- inserted by the claim/recovery service in the same transaction as the claim transition

### activity_logs
- `activity_id` PK
- `actor_user_id` FK → users nullable
- `event_type`, `target_type`, `target_id`
- `created_at_utc`, `outcome`, `correlation_id`
- limited structured, non-sensitive metadata
- never log password, session token, CSRF token, SAS URL, claim statement/evidence, or raw secrets

### recoveries
- `recovery_id` PK
- `claim_id` FK → claims (not unique; multiple recovery attempts may exist after audited void/recovery cycles)
- `found_report_id` FK → reports
- `lost_report_id` FK → reports nullable
- `status` CHECK in COMPLETED, VOIDED
- `completed_by_moderator_id`, `completed_at_utc`
- `voided_by_moderator_id`, `voided_at_utc`, `void_reason_code` nullable
- snapshots of report IDs, prior report status/version, and resulting versions to support safe audited void/reversal

### claim_evidence
- `evidence_id` PK
- `claim_id` FK → claims
- `uploaded_by_user_id` FK → users
- private Blob key (unique), sanitized original filename, content type, size, upload status, uploaded_at_utc
- description nullable; deleted/purge timestamps nullable
- optional; maximum three active evidence images per claim

## 3.3 Relationships

- One role → many users.
- One user → many sessions.
- One user → many reports.
- One category/location → many reports.
- One report → zero or more attachments.
- One LOST report ↔ many FOUND reports through matches.
- One FOUND report → many claims over time.
- One report → many status-history records.
- One actor → many activity events.

## 3.4 Constraints and integrity

Required:
- PK on every entity.
- FK relationships as above.
- UNIQUE normalized email.
- CHECK report type, statuses, score ranges, positive attachment size.
- Category/location references must exist and be active when creating a report.
- A match must reference one LOST and one FOUND report; enforce in service logic and database constraints where feasible.
- Claim report must be FOUND and eligible at submission time.
- A user cannot claim their own found report.
- At most one VERIFIED/RECOVERED claim per FOUND report; at most one VERIFIED/RECOVERED claim per linked LOST report.
- At most one successful recovery per FOUND report and per linked LOST report.
- A report may be marked RESOLVED only through successful claim/recovery workflow.
- Report status and status history must be changed consistently.
- No client-supplied role is accepted as authoritative.

## 3.5 Indexes

Create indexes based on real access patterns:
- `users(email_normalized)` unique
- `sessions(user_id, expires_at_utc)` and session lookup key
- `reports(report_type, status, created_at_utc)`
- `reports(category_id, location_id, occurred_on)`
- `reports(reporter_user_id, created_at_utc)`
- `matches(lost_report_id, score DESC)`
- `matches(found_report_id, score DESC)`
- `claims(found_report_id, status, created_at_utc)`
- filtered unique indexes for claim concurrency invariants and recovery winner uniqueness
- `matching_jobs(status, next_attempt_at_utc, lease_expires_at_utc)`
- `claims(claimant_user_id, created_at_utc)`
- `report_status_history(report_id, changed_at_utc)`
- `claim_status_history(claim_id, changed_at_utc)`
- `activity_logs(created_at_utc, event_type)`

Validate indexes with query plans and realistic sample data; avoid indiscriminate indexing.

## 3.6 Database deliverables for course/rubric

- ER diagram.
- Normalization rationale.
- PK/FK/CHECK/UNIQUE evidence.
- At least one meaningful JOIN query.
- Index justification.
- Analytics view.
- Narrow SQL Server report status-history trigger (frozen); include trigger demonstration in course evidence.
- Transaction demonstration for approval/recovery.
- Migration history and seed script.

**Frozen trigger decision:** use one narrow SQL Server trigger for report status history. The application sets actor/reason/correlation context transactionally before a report status transition. Claim status history and general audit are application-managed in the same transaction. Do not duplicate report status-history writes in application code.

---

# 4. Domain states and workflows

## 4.1 Report state machine — frozen

States:
- `ACTIVE`: open, student-visible subject to privacy rules, claim-eligible, and matching-eligible.
- `RESOLVED`: successful recovery recorded by moderator.
- `WITHDRAWN`: owner voluntarily withdrew an ACTIVE report.
- `CLOSED`: moderator administratively closed an invalid, duplicate, inappropriate, or otherwise unsuitable report.

Rules:
- New reports start ACTIVE.
- Only ACTIVE reports accept claims and participate in matching.
- Owner may edit only their own ACTIVE report and only approved user-editable fields.
- Owner may withdraw own ACTIVE report only when no PENDING or VERIFIED claim references it as FOUND or linked LOST.
- Moderator may close an ACTIVE report only after all associated PENDING/VERIFIED claims have been made terminal (reject/cancel/revoke with reason). No force-close shortcut.
- Recovery transaction may transition the FOUND report and linked LOST report to RESOLVED.
- Owner cannot reopen any terminal report. Moderator may reopen WITHDRAWN/CLOSED to ACTIVE with reason. RESOLVED may return to ACTIVE only as part of an audited recovery void/correction.
- No automatic expiry; no hard delete.
- Terminal reports are visible to their owner and moderators, not in student browse/matching.
- Status transitions use optimistic version checks and audit/history.

## 4.2 Claim state machine — frozen

States:
- `PENDING`: submitted; awaiting moderator decision.
- `VERIFIED`: moderator accepts evidence; recovery has not yet been recorded.
- `RECOVERED`: recovery transaction completed; terminal except exceptional recovery void.
- `REJECTED`: moderator rejected or revoked verification; terminal.
- `CANCELLED`: claimant cancelled before recovery; terminal.

Rules:
- Claim always targets one ACTIVE FOUND report.
- `lost_report_id` is optional; if supplied, it must be an ACTIVE LOST report owned by the claimant.
- Claimant cannot claim their own FOUND report.
- Claim submission does not change report status.
- Multiple PENDING claims are allowed per FOUND report.
- A claimant may have at most one PENDING/VERIFIED claim per FOUND report.
- At most one VERIFIED claim may exist per FOUND report and per linked LOST report.
- While a FOUND report has a VERIFIED claim, new claims against it are blocked. Existing PENDING claims remain pending.
- Claimant may cancel PENDING or VERIFIED before recovery. Moderator may reject PENDING or revoke VERIFIED with reason.
- Moderator cannot verify/recover a claim if they are its claimant or owner of the FOUND report.
- Report owner/finder cannot approve claims; moderator verification is mandatory.
- Information requests are audit events, not a separate state.

## 4.3 Verification, recovery, and claim/report transaction rules

Verification and physical recovery are distinct.

### Verification

- Moderator verifies evidence and moves PENDING → VERIFIED.
- FOUND report remains ACTIVE; report status does not change.
- Other PENDING claims remain PENDING.
- No new claims are accepted for that FOUND report while VERIFIED exists.
- Verification is serialized against other claim verification using SQL row locks/conditional updates and filtered unique indexes.

### Recovery completion (single Azure SQL transaction)

1. Lock claim, FOUND report, optional linked LOST report, and conflicting claim rows in deterministic ID order.
2. Check claim is VERIFIED; reports are ACTIVE; no other VERIFIED/RECOVERED claim conflicts with the FOUND or linked LOST report; moderator is authorized and not conflicted.
3. Insert recovery record with prior report statuses/versions.
4. Transition selected claim VERIFIED → RECOVERED.
5. Transition FOUND report ACTIVE → RESOLVED.
6. If linked LOST report is still ACTIVE and owned by claimant, transition it ACTIVE → RESOLVED.
7. Reject all other PENDING claims linked to the same FOUND report or same LOST report with reason `OTHER_CLAIM_RECOVERED`.
8. Write claim history and audit events; report status history is generated by trigger.
9. Commit. If any step fails, roll back all SQL changes.

No item may have more than one successful recovery. A LOST report may be referenced by multiple PENDING claims against different candidate FOUND reports, but only one can become VERIFIED and only one can be recovered.

### Recovery void/correction

- Exceptional moderator-only action; mandatory reason and audit trail.
- Recovery is marked VOIDED; claim returns RECOVERED → VERIFIED.
- Reopen only the report(s) whose RESOLVED transition was caused by this recovery and whose current status/version still matches the recorded post-recovery state.
- If report state/version has since changed, do not automatically reopen; require moderator reconciliation.
- Previously REJECTED competing claims remain terminal; they are not automatically reopened.
- Void and report/claim transitions occur in one SQL transaction.

### Claim/recovery transaction invariants

- Report withdrawal/closure is blocked while any PENDING/VERIFIED claim references the report as FOUND or linked LOST.
- Owner edits to a report are blocked while any PENDING/VERIFIED claim references it. Moderator correction remains possible with reason/audit.
- When one claim is recovered, conflicting PENDING claims against both the FOUND and linked LOST reports are rejected in the same transaction.
- Claims may target a FOUND report without a linked LOST report.
- Reopening a WITHDRAWN/CLOSED report does not reopen prior claims.
- Reopening a RESOLVED report requires recovery void/correction first.

## 4.4 Report creation and photo workflow

Report photos are optional; one photo per report, maximum 5 MB. Claim evidence photos are optional, maximum three per claim and 5 MB each.

1. Validate report/claim data and upload permissions.
2. Validate actual content signature and allow only JPEG, PNG, or WebP; reject SVG and unknown types.
3. Upload through backend to private Blob using a random object key.
4. Insert SQL attachment/evidence metadata.
5. If SQL metadata insert fails after Blob upload, attempt Blob deletion and record cleanup-needed if deletion fails.
6. Report creation succeeds without a photo if upload fails; return a clear attachment error/retry affordance. Claim submission may similarly succeed without optional evidence.
7. Retrieval is authorized by backend; do not expose permanent public Blob URLs or storage credentials.
8. Replace/delete operations use compensation and audit.
9. Report photos and claim evidence are purged 90 days after their report/claim reaches a terminal state; a maintenance command performs purge and logs the action. Active records retain their photos.

# 5. API contract

## 5.1 API conventions

- Prefix: `/api`; REST/JSON; UUID identifiers; UTC ISO 8601 timestamps.
- Pagination uses `page` and `page_size`.
- Backend validation with typed schemas; reject unknown fields.
- Responses must not expose DB model objects directly.
- FastAPI OpenAPI is generated from the implementation schemas.
- The complete request/response schemas, status codes, pagination ordering, validation, error format, privacy, and route semantics are frozen in `IMPLEMENTATION_CONTRACTS.md`. That file is normative for implementation detail.

## 5.2 Authentication

- `POST /api/auth/register`
- `POST /api/auth/login`
- `POST /api/auth/logout`
- `GET /api/auth/me`

Registration:
- accept display name, email, password;
- normalize email;
- hash password with Argon2id;
- assign STUDENT role server-side;
- never accept role in registration payload.

Login:
- generic invalid-credentials error;
- create opaque random session token;
- persist session metadata server-side;
- set Secure, HttpOnly, SameSite cookie;
- rotate session ID on login.

Logout:
- revoke server-side session;
- expire cookie.

## 5.3 Reports

- `GET /api/reports` — filters: type, status, category, location, date range, pagination.
- `POST /api/reports` — create report (student or moderator account; moderator-created reports are subject to independent moderator review).
- `GET /api/reports/{report_id}` — retrieve visible report.
- `PATCH /api/reports/{report_id}` — owner editable fields; moderator correction fields only with reason and audit.
- `POST /api/reports/{report_id}/withdraw` — owner withdrawal of ACTIVE report.
- `POST /api/moderation/reports/{report_id}/close` — moderator administrative closure.
- `POST /api/moderation/reports/{report_id}/reopen` — moderator reopen of WITHDRAWN/CLOSED report; RESOLVED reopen only through recovery void.
- `POST /api/reports/{report_id}/photo` — upload optional photo.
- `GET /api/reports/{report_id}/photo` — authorized backend photo stream (no permanent public Blob URL).

Report creation fields include type, category, location, title, description, and item date. Photo upload is a separate follow-up request after report creation; photo failure does not roll back the report. Never trust reporter ID from payload; derive actor from session. See `IMPLEMENTATION_CONTRACTS.md` for the complete route and schemas.

## 5.4 Matching

- `GET /api/reports/{report_id}/matches` — read persisted match candidates.
- `POST /api/reports/{report_id}/matches/recalculate` — explicit recalculation, owner or moderator only; rate-limited and audited.

Match response includes:
- match ID;
- counterpart report ID;
- safe report display fields;
- total score;
- factor score breakdown;
- deterministic explanation;
- calculation timestamp;
- algorithm version.

No ownership probability, claim evidence, private claimant notes, or hidden user information.

## 5.5 Claims and moderation

- `POST /api/reports/{found_report_id}/claims`
- `POST /api/claims/{claim_id}/evidence` — upload optional private evidence photo (claimant only, before terminal state).
- `GET /api/claims/{claim_id}/evidence/{evidence_id}` — authorized evidence stream for claimant or moderator.
- `GET /api/me/claims`
- `GET /api/moderation/claims?status=PENDING`
- `GET /api/moderation/claims/{claim_id}`
- `POST /api/moderation/claims/{claim_id}/verify`
- `POST /api/moderation/claims/{claim_id}/reject` (PENDING → REJECTED only)
- `POST /api/moderation/claims/{claim_id}/revoke-verification` (VERIFIED → REJECTED with revocation reason)
- `POST /api/claims/{claim_id}/cancel` (claimant only, PENDING/VERIFIED)
- `POST /api/moderation/claims/{claim_id}/recover` (VERIFIED → RECOVERED and report resolution)
- `POST /api/moderation/recoveries/{recovery_id}/void` (exceptional correction)
- `POST /api/moderation/claims/{claim_id}/request-information` (audit event, no state transition)

Claim submission:
- authenticated student;
- FOUND report ACTIVE and not currently locked by a VERIFIED claim;
- claimant is not FOUND report owner;
- optional linked LOST report must be ACTIVE and claimant-owned;
- claim statement required; evidence photo optional;
- backend derives claimant identity from session.

Moderator actions:
- verify/reject/revoke with reason as applicable;
- record recovery only for VERIFIED claim;
- void recovery only with reason and safe report-version check;
- no self-verification or verification of a claim on a report the moderator owns.

## 5.6 Analytics and audit

- `GET /api/moderation/analytics/summary`
- `GET /api/moderation/activity`

Analytics endpoints expose aggregates only, unless moderator permission explicitly permits record-level access.

## 5.7 Common error format

```json
{
  "error": {
    "code": "REPORT_NOT_ELIGIBLE",
    "message": "This report is no longer eligible for this action.",
    "request_id": "..."
  }
}
```

HTTP mapping:
- `400` malformed/invalid request
- `401` unauthenticated
- `403` authenticated but forbidden
- `404` absent or intentionally concealed resource
- `409` state/concurrency conflict
- `413` file too large
- `415` unsupported media type
- `422` schema/field validation
- `429` rate limit
- `500` unexpected internal failure (generic message)
- `503` dependency unavailable

Never expose SQL errors, stack traces, tokens, or internal storage details.

---

# 6. Matching algorithm and lifecycle — frozen `match-v1`

## 6.1 Trigger and durability

Matching runs after report creation and matching-relevant edits, and after a report becomes ACTIVE again. Report status/matching-version changes, match invalidation, and a durable matching work item are written in the same SQL transaction. Matching failure never rolls back a report write.

A SQL-backed `matching_jobs` table is the durable outbox/work queue; no external broker is used. After the report transaction commits, the API attempts immediate matching for prompt feedback. A FastAPI lifespan/request-driven worker also polls/leases due jobs at startup and during normal API traffic; an always-on continuous poller may be used only on a plan that supports it, but is not required for correctness. A job includes report ID, matching version, algorithm version, attempt count, next attempt, lease expiry, status, and sanitized last error. Lease/conditional updates prevent multiple App Service instances from processing the same job simultaneously. Jobs are idempotent. Retry with exponential backoff capped at one hour, maximum eight attempts; exhausted jobs become DEAD and are visible to the authorized deployment operator through the matching-jobs CLI (no ADMIN role). Explicit recalculation requeues the existing row for the same report/matching-version/algorithm idempotency key (or inserts one if absent); it does not create a duplicate job row. Pending jobs remain in SQL through App Service restarts and are processed when the app starts/receives traffic.

If report is terminal/ineligible, invalidate affected matches and do not enqueue a scoring job. If report is active, enqueue matching after commit. If a newer report version exists when a job runs, mark the old job SUPERSEDED and process the current version.

## 6.2 Eligibility and candidate generation

- Only ACTIVE LOST/FOUND reports are eligible.
- Compare opposite types only; canonical orientation is LOST ID + FOUND ID.
- Same-type pairs are impossible.
- Campus reports only; no external geographic search.
- Candidate visibility rules still apply.
- Event date is `occurred_on`, not report creation timestamp.

## 6.3 Scoring rules

Each factor is normalized to 0–100. Total score:

`total = category × 0.40 + location × 0.25 + date × 0.25 + keyword × 0.10`

Weights retained from the research specification:
- category: 40%
- location: 25%
- date: 25%
- keyword: 10%

Factor rules:

**Category:** exact category ID = 100; different category = 0. Categories are flat for `match-v1`; no hierarchy/related-category inference.

**Location:** location records have a parent zone/area. Exact location ID = 100; different locations under the same zone = 60; different zones = 0. Missing/unknown location is not treated as a match (location is required on reports).

**Date:** let `d` be absolute calendar-day difference between LOST and FOUND `occurred_on`. Candidate window is `d <= 30`. Score is `max(0, 100 × (1 − d/30))`; at 30 days the score is zero. Outside 30 days is excluded before scoring.

**Keywords:** combine title and description, lowercase, Unicode-normalize, tokenize alphanumeric terms, remove punctuation and a fixed documented English stopword list, discard tokens shorter than 2 characters, then compute Jaccard similarity between unique token sets ×100. Empty sets score 0. No AI, embeddings, external model, stemming, or nondeterministic semantic inference.

**Threshold:** store/display as POTENTIAL only if total score ≥ 50. Scores below threshold are not presented as potential matches. If a previously stored pair falls below threshold, retain its record as SUPPRESSED rather than deleting it.

## 6.4 Deterministic ranking

Sort by:
1. total score descending;
2. date difference ascending;
3. location score descending;
4. report creation timestamp ascending;
5. counterpart report UUID ascending (stable final tie-break).

Round display score to one decimal; calculations use full precision and persisted score uses decimal precision (not binary float). Explanations include factor values and rule labels, not an ownership probability.

## 6.5 Match persistence and states

Persist: canonical LOST/FOUND IDs, total and factor scores, explanation, algorithm version, calculated timestamp, LOST/FOUND report versions, match status, invalidation timestamp/reason.

Match states:
- `POTENTIAL`: current, eligible, score at/above threshold.
- `SUPPRESSED`: current pair calculated but below threshold.
- `INVALIDATED`: report version/status changed; retained for provenance.
- `DISMISSED`: moderator explicitly dismissed with reason; preserved for the same report matching versions and algorithm version. A materially changed report version or new algorithm version may produce a fresh potential match.

Unique key: `(lost_report_id, found_report_id, algorithm_version)`; recalculation updates the current version row idempotently. Preserve prior calculated fields in audit history when updated. A new algorithm version uses a separate row/version.

## 6.6 Invalidation and reverse candidate effects

When a report changes matching-relevant content or eligibility:
- increment `matching_version`;
- invalidate all POTENTIAL/SUPPRESSED match records involving it;
- insert a matching job for the changed ACTIVE report;
- recompute the pair against opposite candidates, including pairs where it was the candidate for another report (canonical pair row means no separate directional duplicate);
- ensure old results cannot remain displayed as current if either report version/status differs.

Terminal report transition invalidates all matches involving it and does not run matching. Reopening to ACTIVE increments matching_version and enqueues matching.

## 6.7 Algorithm versioning

Current version is `match-v1`. Any scoring/filter/tokenization/threshold change increments version and requires a documented migration/recalculation plan. Do not silently rewrite historical score semantics.

# 7. Authentication, authorization, and security

## 7.1 Password and session handling

- Argon2id password hashing.
- Never plaintext or reversible password storage.
- Random high-entropy opaque session token; store only its SHA-256 digest server-side (never raw token). Exact cookie/session/CSRF values and lifecycle are frozen in `IMPLEMENTATION_CONTRACTS.md`.
- Cookie: host-only API cookie, `Secure`, `HttpOnly`, `SameSite=Lax`.
- Production frontend and API must use custom hostnames under the same registrable domain (e.g. app.example.edu and api.example.edu) so browser requests are same-site while remaining separate origins. This is a deployment prerequisite; do not deploy cookie auth across unrelated default Azure domains.
- Frontend API requests use `credentials: include`; CORS allows only the exact frontend origin.
- Expiration and revocation on logout.
- Session rotation on login and privilege change.
- Rate-limit login/register endpoints.
- Generic login failure message.
- Deactivate/revoke sessions when account is disabled.

## 7.2 Cross-origin, CORS, CSRF

Frontend Azure Static Web Apps and API Azure App Service may be separate origins.

- Allow only configured frontend origin(s), never wildcard with credentials.
- Credentialed requests must use explicit origin.
- Cookie-authenticated state-changing requests require CSRF protection.
- CSRF token is generated per server-side session, returned through `GET /api/auth/csrf`, and sent in `X-CSRF-Token` on every state-changing request. Backend compares its digest with session state and validates exact `Origin` against configured frontend origin. See `IMPLEMENTATION_CONTRACTS.md`.
- CORS is not a substitute for CSRF protection.
- Local dev uses explicit localhost origins and credentials; production origins are environment configuration.
- If same-site custom domains cannot be obtained, deployment is blocked until the project owner explicitly approves an alternative topology; do not silently switch to `SameSite=None` cross-site cookies.

## 7.3 Permission matrix

| Action | Student | Moderator |
|---|---|---|
| Register/login/logout | Yes | Yes |
| Create report | Yes | Yes; moderator-owned reports require a different moderator for claim verification/recovery |
| Browse public/eligible reports | Yes | Yes |
| Edit own report | Yes, allowed fields | Yes, moderation fields only |
| Edit another user's report | No | Only explicit moderation permission |
| View potential matches | Authorized report visibility | Yes |
| Submit claim | Yes, eligible report only | **No** |
| View own claim | Yes | No moderator claims; moderators view claims through moderation endpoints |
| View claim evidence | Claimant own claim | Authorized moderator |
| Approve/reject claim | No | Yes |
| Mark recovered | No | Via approved workflow |
| View audit events | Own safe activity if included | Moderator only |
| View analytics | Limited public/student metrics if any | Moderator |

Moderator account creation must not allow public self-registration as MODERATOR. Use an interactive backend CLI command (`create-moderator`) that prompts for display name/email/password, normalizes email, hashes with Argon2id, and creates a new moderator only when invoked by an authorized operator. If normalized email already exists, refuse; do not silently update role or password. Never embed a default moderator password or allow role elevation through public API.

## 7.4 Upload security

Frozen upload requirements:
- JPG/PNG/WebP allowlist;
- maximum 5,000,000 bytes (decimal MB);
- one photo per report unless scope explicitly changes;
- validate actual file content, not only extension/MIME;
- private Blob container;
- random object keys;
- sanitize filename;
- no direct public Blob URLs;
- authorized retrieval via backend stream only; do not issue SAS URLs in v1;
- re-encode accepted images and strip metadata/EXIF (mandatory);
- store no SAS URL in SQL/audit.

## 7.5 Application security

- Parameterized SQL/ORM queries.
- Output encoding/safe React rendering.
- Validate request fields server-side.
- Prevent mass assignment: accept only schema-approved fields.
- Do not accept user/role/reviewer IDs from untrusted payload.
- Secrets in Azure App Service configuration/Key Vault if available; never commit secrets.
- HTTPS-only.
- Azure SQL firewall/network restrictions.
- Least privilege for DB and Blob identities.
- Audit sensitive actions.
- No secrets/claim evidence in application logs.
- File retrieval must authorize report/attachment access before streaming bytes from the backend; v1 does not issue SAS URLs.

---

# 8. Attachment lifecycle

1. User submits upload to backend.
2. Backend verifies report ownership/permission.
3. Validate size, extension, actual MIME/signature, and content.
4. Generate random Blob key.
5. Upload to private Blob.
6. Insert attachment metadata in SQL.
7. If metadata insert fails, delete Blob or mark orphan cleanup.
8. On retrieval, backend checks authorization.
9. Backend returns an authorized stream only; v1 does not issue SAS URLs.
10. Delete/replace behavior must clean SQL and Blob consistently; record audit event.

Blob is not publicly readable. Account keys never reach frontend.

---

# 9. Audit, logging, and history

## 9.1 Required event classes

- registration success/failure where useful;
- login success/failure and logout;
- report created/updated/closed/moderated;
- attachment uploaded/deleted;
- match calculation/recalculation/failure;
- claim submitted;
- claim approved/rejected;
- recovery completed;
- moderator access to sensitive claim data where policy requires;
- authorization failures for sensitive actions.

## 9.2 Data minimization

Do not log:
- passwords/password hashes;
- session/CSRF tokens;
- SAS URLs;
- raw claim evidence;
- unnecessary personal data;
- request bodies wholesale.

## 9.3 Audit vs status history

- `report_status_history` records report lifecycle transitions.
- `activity_logs` records broader actor/system events.
- They serve different purposes; avoid treating one as a replacement for the other.
- Claim status history is required for all claim state transitions and is committed in the same transaction.

---

# 10. Analytics and Power BI

## 10.1 SQL view/read model

Provide a reporting view such as `vw_recovery_analytics` or a set of aggregate queries with metrics:
- count of LOST reports;
- count of FOUND reports;
- active reports;
- claims submitted;
- claims approved/rejected;
- recovered items;
- recovery rate;
- reports/claims by category;
- reports by location;
- recovery trends by date;
- median/average elapsed time from report creation to recovery.

Frozen definitions: recovery rate = FOUND reports resolved through a completed recovery / all FOUND reports created in the selected period (report cohort), expressed as a percentage; display the cohort period and denominator. Counts by report status are separate. Withdrawn/closed reports remain in the denominator and are visible in status breakdowns; also provide a secondary rate among non-withdrawn FOUND reports if useful, clearly labeled. Recovery-time metric is from report creation to completed recovery. Do not expose claimant names, claim statements, evidence, or moderator notes.

## 10.2 Access

- Power BI Desktop uses a read-only connection/query.
- Analytics must not write operational data.
- Sensitive claimant details must not be exposed in analytics.
- If credentials are required, use a least-privilege read-only database principal.
- Power BI Service publishing/licensing is not assumed.

---

# 11. Error handling, consistency, and performance

## 11.1 General

- Use typed domain errors and stable API error codes.
- Log internal exception details with request/correlation ID; return generic client errors.
- No stack traces in production responses.
- Every multi-record operation has an explicit transaction boundary.
- SQL deadlocks/timeouts handled with bounded retry where safe.
- Idempotency is required for retryable matching and critical approval operations.

## 11.2 Consistency rules

- Report creation/update must commit before matching runs.
- Matching failure cannot invalidate the report.
- Match records are derived and versioned.
- Claim approval/recovery is atomic.
- Blob and SQL coordination uses compensation/cleanup, not fictional distributed transactions.
- Analytics is read-only.
- Audit/status history for important SQL workflow transitions is committed with the transaction.

## 11.3 Performance

- Paginate report, claim, and audit lists.
- Candidate filtering before matching scoring.
- Index actual query predicates.
- Avoid N+1 queries.
- Avoid repeated Blob downloads in report listing.
- Use bounded candidate counts if necessary, but document selection/ranking correctness.
- Do not add caching/queues before measurements justify them.

---

# 12. Frontend implementation contracts

## 12.1 Main routes/views

- Register/login
- Student home/report browse
- Create/edit report
- Report detail
- Potential matches
- Claim submission and own claims
- Moderator claim queue
- Moderator claim detail/review
- Moderator activity/audit
- Analytics dashboard

## 12.2 UI behavior

- Loading, empty, error, and success states for every async operation.
- Clear LOST/FOUND distinction.
- Show match score and factor explanation with a “potential match only” disclaimer.
- Hide role-inappropriate controls but rely on backend enforcement.
- Confirm destructive/irreversible actions.
- Prevent duplicate submissions while requests are in flight.
- Display conflict errors when report state changed.
- Sensitive claim evidence visible only to claimant/moderator.

---

# 13. Testing and acceptance criteria

## 13.1 Backend tests

- Auth registration/login/logout/session expiry.
- Argon2 verification and no plaintext password persistence.
- RBAC and ownership checks.
- Report validation and lifecycle transitions.
- Matching eligibility, each scoring factor, weight sum, deterministic output, candidate orientation, invalidation, persistence, recalculation idempotency.
- Claim submission restrictions.
- Concurrent claim approvals cannot recover one report twice.
- Transaction rollback on failure.
- Attachment validation and authorization.
- Audit events are written for important actions.
- Analytics view/query correctness.

## 13.2 Frontend tests

- Forms and validation.
- Auth/session states.
- Report list/filter/detail.
- Match display/explanation.
- Claim and moderator flows.
- Unauthorized UI state and backend error handling.
- Upload constraints and failure/retry states.

## 13.3 Integration tests

- React/API integration (where test tooling permits).
- API ↔ Azure SQL or SQL-compatible test database.
- Blob adapter using test storage/emulator or mocked integration boundary.
- Full report → matching → claim → moderator approval → recovery → analytics workflow.
- Failure injection for Blob/SQL and matching failures.

## 13.4 Acceptance criteria (project-level)

- Students can register/login and perform permitted actions.
- Reports are persisted and browsable.
- Photos are private and authorized.
- Report creation/update produces persisted deterministic matches using the documented algorithm.
- Match records update/invalidate when relevant report data changes.
- Students can submit eligible claims.
- Moderators can review and decide.
- Approval/recovery is transactionally consistent.
- Audit and status history are retained.
- Analytics metrics reconcile with SQL operational data.
- Backend authorization cannot be bypassed through frontend manipulation.
- Application deploys on selected Azure services with secrets excluded from Git.
- Test evidence, architecture/ER diagrams, deployment instructions, and viva explanation are included.

---

# 14. Azure deployment and configuration

## 14.1 Target resources

- Azure Static Web Apps — frontend
- Azure App Service — FastAPI
- Azure SQL Database — relational data
- Azure Blob Storage — private photos
- Power BI Desktop — analytics

## 14.2 Environment configuration

Provide `.env.example` / documented App Service settings for:
- environment name;
- frontend allowed origin;
- database connection string;
- session secret/config;
- Blob account/container configuration;
- upload limit;
- session expiry;
- logging level;
- matching algorithm version;
- cookie/CORS/CSRF settings.

No real secret is committed.

## 14.3 Deployment process

1. Create/verify Azure for Students subscription/resource availability.
2. Provision Azure SQL and configure firewall/network access.
3. Provision private Blob container.
4. Provision App Service and configuration.
5. Deploy FastAPI.
6. Run migrations using controlled deployment step.
7. Provision Static Web App and configure API origin.
8. Configure CORS/cookie/CSRF and HTTPS.
9. Seed categories, locations, role records, and moderator account securely.
10. Verify health, auth, report creation, Blob upload, matching, claim approval, and analytics.
11. Capture deployment evidence and cost/service configuration.

Do not assume quota/plan is free; check portal before provisioning.

---

---

# 16. Implementation sequence

The project is implemented as a complete system in a coordinated sequence, not as a reduced feature MVP. Dependencies determine build order:

1. Repo/tooling, configuration, CI/test foundation.
2. SQL schema/migrations, status-history trigger, seed/reference data.
3. Auth, sessions, RBAC, moderator provisioning CLI.
4. Reports, report state machine, status/audit history.
5. Private Blob/photo integration and cleanup.
6. Deterministic matching `match-v1`, match persistence, SQL outbox worker, invalidation/retry.
7. Claims, moderation, evidence handling.
8. Recovery transaction, report resolution, competing claim rejection, recovery void.
9. Audit logging and retention maintenance.
10. SQL analytics view/API.
11. Student frontend flows.
12. Moderator UI and analytics.
13. Integration/security/concurrency tests.
14. Azure domain/resource verification, deployment and tests.
15. Demo, report, diagrams, viva notes.

# 17. Coding-agent execution rules

- Read `README.md`, `AGENTS.md`, Architecture, Blueprint, Tech Stack, scope, decisions, readiness audit, and `IMPLEMENTATION_CONTRACTS.md` before coding. The contracts file is mandatory for exact API/schema/security behavior.
- Implement only documented behavior.
- Do not invent endpoints, states, schema fields, or features.
- If a decision is unresolved, stop and report options/impact.
- Do not change architecture or tech stack without owner approval.
- Keep frontend/backend contracts synchronized.
- Add tests with each feature.
- Use migrations for DB changes.
- Do not commit, push, deploy, or provision cloud resources without explicit owner instruction.
- Report changed files, decisions, tests, and known gaps after each task.
- Never claim tests/deployment succeeded unless actually run.

---

# 18. Blueprint freeze checklist

- [x] Architecture and Tech Stack cross-reviewed.
- [x] Report lifecycle and owner withdrawal finalized.
- [x] Claim lifecycle, simultaneous claims, verification, and recovery finalized.
- [x] Matching scoring, threshold, candidate filtering, and ranking finalized.
- [x] Matching persistence, invalidation, and durable retry finalized.
- [x] Auth/session/CORS/CSRF topology finalized.
- [x] Moderator provisioning finalized.
- [x] Photo/evidence upload and retention policy finalized.
- [x] Analytics metrics/denominators finalized.
- [x] Audit retention and trigger ownership finalized.
- [x] Transaction boundaries and concurrency invariants finalized.

# 19. Frozen design decisions and implementation acceptance baseline

This section resolves prior open items. It supersedes earlier text that called report/claim states, matching rules, CSRF topology, moderator provisioning, photo policy, analytics definitions, or matching retry behavior “pending” or “to be finalized.”

## 19.1 Report lifecycle decision table

| Transition | Actor | Preconditions | Effect |
|---|---|---|---|
| Create → ACTIVE | Student | Valid input | Audit; version=1; matching_version=1; matching job inserted |
| ACTIVE → ACTIVE edit | Owner | Owner, allowed fields, expected version; no PENDING/VERIFIED claim references report | version++; matching_version++ only if matching fields changed; invalidate/enqueue as needed |
| ACTIVE → WITHDRAWN | Owner | No PENDING/VERIFIED claim references report as FOUND or linked LOST | reason fixed as owner withdrawal; invalidate matches; no claims/matching |
| ACTIVE → CLOSED | Moderator | Reason code; all related PENDING/VERIFIED claims terminalized first | invalidate matches; audit; no matching |
| ACTIVE → RESOLVED | Recovery transaction | Completed recovery | recovery workflow changes report(s); invalidate matches |
| WITHDRAWN/CLOSED → ACTIVE | Moderator | Reason, expected version, no live claim conflict | version++; matching_version++; enqueue matching |
| RESOLVED → ACTIVE | Moderator recovery-void workflow only | Recovery void; prior status/version provenance still safe | version++; matching_version++; enqueue matching |

`RESOLVED` means recovery; `CLOSED` means administrative closure; `WITHDRAWN` means owner withdrawal. No EXPIRED state or automatic expiry. Reports are not hard-deleted. Moderator correction of terminal report fields is allowed with reason/audit, but does not make it match-eligible.

## 19.2 Claim lifecycle decision table

| Transition | Actor | Preconditions |
|---|---|---|
| Create → PENDING | Student claimant | FOUND ACTIVE; not owner; no VERIFIED claim on FOUND; no existing PENDING/VERIFIED same claimant+FOUND; optional LOST ACTIVE and claimant-owned |
| PENDING → VERIFIED | Moderator | Expected claim version; FOUND ACTIVE; no other VERIFIED/RECOVERED claim for FOUND; no VERIFIED claim for linked LOST; moderator not claimant/report owner |
| PENDING → REJECTED | Moderator | Reason required |
| PENDING → CANCELLED | Claimant | Own claim |
| VERIFIED → REJECTED | Moderator | Reason; no recovery |
| VERIFIED → CANCELLED | Claimant | Own claim; no recovery |
| VERIFIED → RECOVERED | Moderator recovery transaction | Physical handover confirmed; all conflicting constraints pass |
| RECOVERED → VERIFIED | Moderator recovery-void workflow | Recovery void with reason; safe report version/status reversal |

PENDING and VERIFIED are non-terminal. RECOVERED, REJECTED, CANCELLED are terminal except recovery void. At most one VERIFIED claim per FOUND report and per linked LOST report; multiple PENDING candidate claims may refer to the same LOST report. Recovery rejects competing PENDING claims sharing the FOUND report or linked LOST report.

## 19.3 Concurrency, SQL constraints, and transaction rules

- SQL Server/Azure SQL conditional updates and `UPDLOCK`/`HOLDLOCK` in narrowly scoped transactions serialize claim verification, report withdrawal/closure, and recovery. Lock involved report IDs in deterministic order.
- Filtered unique indexes enforce at most one VERIFIED/RECOVERED claim per FOUND report, at most one VERIFIED claim per LOST report, and at most one PENDING/VERIFIED claim per claimant+FOUND report. A separate unique invariant allows only one completed recovery per FOUND and per LOST report. If a SQL Server filtered-index predicate cannot represent a rule, use a persisted computed guard key with a unique index.
- PENDING claims may reference the same LOST report across different FOUND candidates. Do not impose a uniqueness constraint on `lost_report_id` for all active claims.
- Recovery completion, competing-claim rejection, report resolution, recovery insert, claim history, and audit are one SQL transaction.
- Claim cancellation/recovery race: conditional state/version update determines the winner; loser receives 409.
- Report withdrawal/claim submission race: both lock the same report row; only one action can pass the eligibility check.
- Report status history is generated by a narrow SQL Server trigger on status change; claim history and application audit are written by the service in the same transaction. No duplicate report-status history insert in the application.
- Audit event table is append-only from application perspective. Audit events are retained 365 days. Report/claim status history is retained with its SQL workflow record. Report/claim photo bytes and attachment metadata are purged 90 days after associated report/claim becomes terminal. SQL workflow/report records remain for project audit and analytics; account deactivation revokes sessions.

## 19.4 Moderator, security, and privacy decisions

- Moderator accounts are provisioned through interactive operator CLI; no public moderator registration or role self-elevation.
- Moderators cannot verify/recover their own claim or a claim on a report they own. Another moderator must act.
- Report owner sees report lifecycle and a generic `has_active_claim` boolean (whether at least one PENDING/VERIFIED claim exists); does not see claimant identity, count, statement, or evidence at any point. Claimant sees their own claim. Moderators see claim statement/evidence. Other students see no claim details.
- Report photo is optional, max one per report, max 5 MB. Claim evidence photos are optional, max three per claim, max 5 MB each. JPEG/PNG/WebP only; reject SVG. Validate signature, not just extension/MIME. Private Blob; random keys; backend-authorized retrieval.
- Claim statement/evidence are sensitive. Never log their contents or expose them in matching/analytics.
- Production app/API use same-site custom domains under one registrable domain, exact CORS allowlist, host-only Secure/HttpOnly/SameSite=Lax API session cookie, credentials-enabled frontend fetch, CSRF session token in `X-CSRF-Token`, and strict Origin validation. If same-site custom domain is unavailable, deployment waits for owner-approved alternative.
- Moderator CLI is the only initial provisioning path; no default credentials.

## 19.5 Matching and retry decisions

- `match-v1` is defined in Section 6: category exact=100/otherwise 0; location exact=100/same zone=60/other zone=0; date max 30 days with linear decay; keyword Jaccard; weighted score 40/25/25/10; threshold 50; deterministic tie-break order.
- A SQL-backed matching outbox is written in the same transaction as report creation/material update. FastAPI worker polls and leases jobs, retries with capped exponential backoff up to eight attempts, marks exhausted jobs DEAD, and resumes after App Service restart. No Kafka/Redis/external broker.
- Report status/field change immediately invalidates affected persisted matches in SQL. Match results carry report version provenance and cannot be shown as current if versions differ.
- Match states: POTENTIAL, SUPPRESSED, INVALIDATED, DISMISSED. Pair key includes algorithm version.
- Matching failure does not roll back report writes. Explicit recalculation is a repair action available to report owner/moderator; DEAD job maintenance is operator CLI only.

## 19.6 Analytics and course evidence

- SQL read-only view/read model provides counts by report type/status, claim/recovery counts, category/location distribution, monthly trends, recovery rate, and time-to-recovery. Power BI Desktop is baseline; Power BI Service is not required.
- Recovery rate denominator and cohort definition are stated in Section 10.1; avoid ambiguous “success rate” labels.
- Trigger evidence: demonstrate the report status-history trigger; transaction evidence: demonstrate claim recovery and competing claim updates; constraints evidence: filtered unique indexes and FK/check constraints.

## 19.7 Final freeze rule

The design is frozen for the agreed F1–F6 scope. Any change to state semantics, matching weights/threshold, security topology, or transactional invariants requires an explicit owner-approved change recorded in `DECISIONS.md` and reflected across Tech Stack/Architecture/Blueprint. Exact package versions, Azure resource tiers/region, quota, domain purchase, and costs are verified at deployment; they do not authorize feature or architecture drift.
