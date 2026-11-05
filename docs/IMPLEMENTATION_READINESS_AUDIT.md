# Repository Contradiction & Implementation-Readiness Audit

**Audit:** FindMyThing documentation repository, frozen v1.0 baseline  
**Audit status:** Initial repository review and specification-closure pass completed; implementation remains not started  
**Purpose:** Determine whether a coding agent with no prior conversation can implement the agreed F1–F6 system without guessing or silently changing owner decisions.

## 1. Executive verdict

**Initial audit verdict (before closure):** The repository had a strong architecture/behavioral blueprint but lacked deterministic implementation contracts. The initial findings below are preserved as an audit trail. The closure pass added `IMPLEMENTATION_CONTRACTS.md`, corrected the identified contradictions, and performed final consistency checks. See §9 for the current readiness status.

**Do not treat this audit as implementation authorization.** The existing implementation gate remains in force.

## 2. Repository reviewed

- `README.md`
- `AGENTS.md`
- `docs/PROJECT_OVERVIEW.md`
- `docs/MVP_SCOPE.md`
- `docs/TECH_STACK.md`
- `docs/COURSE_ALIGNMENT.md`
- `docs/DECISIONS.md`
- `docs/ARCHITECTURE.md`
- `docs/BLUEPRINT.md`
- `docs/CONSISTENCY_REVIEW.md`
- `docs/IMPLEMENTATION_STATUS.md`
- `research/FindMyThing-Technical-Research-Decision-Specification.pdf` (reference authority is explicitly subordinate to frozen owner decisions)

No application source code exists yet, so runtime/code-level consistency cannot be audited.

## 3. Confirmed contradictions / stale wording

### C-01 — Architecture origin-topology text contradicted frozen decision

**Location:** `ARCHITECTURE.md`, §6.4  
**Problem:** The section said “Before implementation, choose and document” the topology and called same-site custom domains merely the preferred direction. Later text and `DECISIONS.md` D-026 make same-site custom domains mandatory.  
**Correction made:** Replaced the tentative language with a single frozen requirement. Domain availability is a deployment verification; if unavailable, deployment pauses for owner approval.

### C-02 — Blueprint upload-security section retained research-stage language

**Location:** `BLUEPRINT.md`, §7.4  
**Problem:** “Research proposal” made the frozen upload rules appear optional/provisional. The same document and D-022 freeze them.  
**Correction made:** Changed the label to “Frozen upload requirements.”

### C-03 — Project lifecycle was stale

**Location:** `PROJECT_OVERVIEW.md`, §7  
**Problem:** It still described documentation planning and approval as future/current phases despite docs already being frozen. A context-free agent could misread project phase.  
**Correction made:** Replaced it with research complete, docs frozen, implementation separately gated, and deployment pending.

### C-04 — Moderator claim-submission permission wording conflicts with the agreed rule

**Location:** `BLUEPRINT.md`, §7.3 permission matrix  
**Problem:** The Moderator cell says “Not as moderator unless explicitly permitted.” The frozen project rule is that moderators cannot submit claims; no exception is authorized. Architecture also says moderators cannot submit claims.  
**Required correction:** Change the cell to an unqualified **No**. Moderator-created reports remain allowed; a different moderator must review/recover claims against them.

### C-05 — Report photo creation flow has two interpretations

**Locations:** `BLUEPRINT.md` §4.4 and §5.3; `ARCHITECTURE.md` §7.2  
**Problem:** API lists report creation and a separate `POST /reports/{id}/photo`, while prose describes report creation with optional photo. It is not fully clear whether the UI submits report first and then photo, or sends a multipart combined request. Both approaches are described in different places.  
**Required correction:** Declare one canonical flow. Recommended consistency with existing endpoints: create report first; upload photo via separate endpoint; report remains successfully created if photo upload fails; provide retry UI. Keep photo replacement semantics explicit.

### C-06 — Blueprint says moderator closure/recovery and matching behavior is frozen, but its API “revoke VERIFIED” route is missing

**Locations:** `BLUEPRINT.md` §4.2/§4.3/§5.5  
**Problem:** Rules explicitly permit moderator revocation of VERIFIED claims, and claim-state decision table says VERIFIED → REJECTED is allowed, but API only lists `/reject` (which appears to cover PENDING rejection). It does not define whether `/reject` also revokes VERIFIED or whether a distinct endpoint is needed.  
**Required correction:** Define a single route contract, e.g. reject endpoint accepts PENDING only and a separate revoke-verification endpoint handles VERIFIED; or define `/reject` as accepting both states and specify behavior. Do not leave it to the coding agent.

## 4. High-priority implementation-contract gaps

These are not necessarily architecture contradictions, but they prevent exact implementation without agent discretion.

### H-01 — API contracts are endpoint inventories, not complete contracts

For most endpoints, the repo does not specify exact request fields/types, response shapes, status codes, required/optional fields, or whether responses are wrapped. Missing/unclear examples include:
- report list/detail/create/update payload and response schema;
- claim submission/verification/rejection/recovery request bodies;
- moderator reason-code fields;
- exact analytics response schema;
- match list response pagination;
- file upload response and replacement behavior;
- session/me response and CSRF token endpoint route.

**Needed:** A single API contract table or OpenAPI-first contract section with request/response examples and status/error behavior.

### H-02 — Pagination is explicitly left to the implementer

**Location:** `BLUEPRINT.md` §5.1: “page/page_size or cursor; choose one.”  
**Problem:** This is a direct instruction to make a design choice after freeze.  
**Needed:** Freeze one approach, page-size maximum/default, ordering, and pagination behavior for each list endpoint.

### H-03 — SQL schema is not fully migration-ready

Entity fields are listed, but many exact types, nullability, defaults, lengths, and keys are unspecified. Examples:
- UUID representation is “UUID or uniqueidentifier”; choose SQL Server `uniqueidentifier` consistently and document Python mapping.
- Claim and report title/description/statement maximum lengths and allowed text rules are absent.
- Several `recoveries` moderator IDs lack explicit FK declarations in the entity section.
- `claim_evidence` lacks a complete FK/metadata lifecycle definition in the field list.
- `matches.explanation` JSON SQL type/storage format and schema validation are not defined.
- `matching_jobs` uniqueness/idempotency key needs exact SQL columns/index definition.
- `report_status_history` trigger context key names and SQL Server session-context handling are not enumerated.
- `version`/`matching_version` initial values and overflow/conditional-update semantics are not fully specified.

**Needed:** Exact schema dictionary or migration specification (column name, SQL type, nullable, default, FK, check, unique/index) for every table.

### H-04 — Reference/seed data is not defined

The schema requires categories, locations, zones, and roles, but no approved seed list or configurable campus setup is provided. The location-zone relationship is essential for matching.  
**Needed:** Decide whether initial categories/locations/zones are owner-provided deployment configuration, sample seed data, or an editable moderator/admin feature. No admin role exists in the role model, so do not silently add one.

### H-05 — Report visibility/privacy rules are incomplete

Terms such as “public/eligible reports,” “subject to privacy,” “safe display fields,” and “authorized report visibility” are used without a precise policy. It is unclear exactly which report fields and reporter identity are visible to:
- unauthenticated users (if any);
- authenticated students;
- report owner;
- moderators;
- claimant before/after recovery.

The report owner is explicitly barred from claimant identity/evidence before recovery, but other report fields and claimant identity after recovery are not comprehensively defined.  
**Needed:** Field-level visibility matrix and decision on whether browsing requires authentication.

### H-06 — Claim and report text validation is unspecified

No exact constraints for title, description, claim statement, display name, email, date ranges, or text normalization are provided. A coding agent may choose arbitrary limits and behavior.  
**Needed:** Define lengths, whitespace rules, email policy (campus-only vs general email), and date validation. Do not assume campus-domain restrictions without owner decision.

### H-07 — Moderator reason codes and audit event taxonomy are not enumerated

The Blueprint requires reason codes for CLOSED/WITHDRAWN/RESOLVED, moderator reopen/correction, rejection/revocation, and recovery void, but exact values and free-text policy are absent. Audit events are listed by broad class, not canonical event names.  
**Needed:** Define stable reason/event code enums, required/optional fields, and which actions require a human-readable note.

### H-08 — Claim “revoke VERIFIED” and reason semantics need consistency

The decision table uses PENDING → REJECTED; prose says moderator may revoke VERIFIED with reason. It is not clear whether the claim status is also REJECTED or a distinct status (it should remain REJECTED per frozen states), and how `decision_reason_code`/`reviewed_by_user_id` are updated on a second decision.  
**Needed:** Specify VERIFIED → REJECTED as a revocation/rejection with audit metadata and whether repeated reviewer metadata is retained in history only.

### H-09 — Session and CSRF implementation still contains discretionary language

**Locations:** `BLUEPRINT.md` §3.2 sessions and §7.1  
**Problem:** Session ID/token storage says “random opaque identifier or hash” and “not raw secret if feasible”; CSRF table says `csrf_token_hash or equivalent ... if chosen by security design`. Later sections freeze CSRF token behavior. This allows conflicting implementations.  
**Needed:** Freeze exact model: cookie name, token generation, token storage (raw token vs hash), token endpoint, rotation/invalidation behavior, session table key, expiry policy, and whether last-seen updates are throttled.

### H-10 — Rate limiting is required but values and mechanism are not defined

Login/register and match recalculation are rate-limited, but no thresholds, window, key strategy, storage, or response behavior is given. Redis is prohibited.  
**Needed:** Define a simple in-process/SQL-backed policy appropriate to single App Service instance, or explicitly defer enforcement to Azure platform controls where supported. Must not introduce Redis.

### H-11 — Photo/evidence retention timing around reopen/void is ambiguous

Photos are purged 90 days after a report/claim becomes terminal. Reports can be reopened; RECOVERED claims can return to VERIFIED after recovery void. The docs do not state whether terminal time is reset, purge is cancelled, or purge is irrevocable after scheduled.  
**Needed:** Define terminal timestamp source, purge schedule, reopening/void effects, and behavior when Blob deletion fails. Avoid purging attachments while the related entity is ACTIVE/nonterminal.

### H-12 — Matching dead-job handling mentions an undefined “admin” role

`BLUEPRINT.md` §6.1 says DEAD jobs are visible to “moderators/admin maintenance,” but only Student and Moderator roles are defined and no endpoint/UI/CLI for inspecting or retrying DEAD jobs is specified.  
**Needed:** Replace “admin” with a defined operator/maintenance CLI or moderator-only capability. Do not add an Admin role by implication.

### H-13 — Matching current-row/upsert provenance and dismissed-match behavior need precise persistence rules

The match unique key is `(lost_report_id, found_report_id, algorithm_version)`, while changed report versions may create a “fresh potential match” but same key implies updating/reusing a row. Text says preserve previous calculated fields in audit history, but no match-history table or exact audit payload is defined.  
**Needed:** Decide whether old match calculation snapshots are stored in activity log, a dedicated match-history table, or only invalidation metadata. Define how DISMISSED is reset for changed report matching versions and what endpoint can dismiss a match (currently not listed).

### H-14 — Report update + match invalidation semantics need exact field mapping

Blueprint says matching_version increments for matching-relevant fields, but does not provide a complete field-to-matching-relevance table. Is title/description, category, location, occurred_on, report type, status all relevant? Type is likely immutable but not explicitly.  
**Needed:** Freeze matching-relevant fields and immutable fields; define which report edits are allowed and whether report type/category/location may be changed after creation.

### H-15 — Recovery conflict rejection is not fully operationally specified

Recovery rejects PENDING claims sharing FOUND or linked LOST. The linked LOST report may have pending claims against other FOUND reports; this rule is documented, but the exact query/lock ordering and how `decision_reason_code`, reviewer, and claim history are populated for automatically rejected claims is not.  
**Needed:** Specify system actor, reason, timestamps, audit/history event, and deterministic locking/query sequence for competing claims.

### H-16 — Azure deployment and database connectivity require concrete implementation guidance

Stack specifies Azure SQL + FastAPI App Service but does not freeze SQLAlchemy driver/connection string format, ODBC/native dependency assumptions, App Service startup command, migration execution strategy, or Blob authentication mechanism (managed identity vs connection string). “Key Vault if available” and “least privilege” are principles, not configuration contracts.  
**Needed:** Pick compatible deployment configuration and credential mechanism before deployment. Package versions can remain implementation-time choices, but must be pinned and verified in CI.

### H-17 — Analytics/dashboard scope has two presentation layers but no exact UI boundary

The project overview says moderator analytics and Power BI Desktop. Blueprint also defines `/api/moderation/analytics/summary` and frontend “Analytics dashboard.” It is unclear whether the browser dashboard is required as a separate UI or Power BI is the sole dashboard.  
**Needed:** Clarify whether both are required: likely lightweight moderator web summary + Power BI Desktop report deliverable, or Power BI only. Define exact metrics in each.

### H-18 — API contract includes CSRF endpoint by implication, not by inventory

The security spec requires fetching a session CSRF token, but API inventory does not define the route (e.g. `GET /api/auth/csrf`) or response body. This blocks frontend auth integration.  
**Needed:** Add explicit route and contract.

## 5. Medium-priority issues

- `README.md` points to the consistency review as a final check, but the old review declares “No known contradiction remains”; this audit supersedes that claim. Update it to reference this audit and distinguish cross-document consistency from coding-readiness.
- `CONSISTENCY_REVIEW.md` does not list `PROJECT_OVERVIEW.md` or `COURSE_ALIGNMENT.md` in its reviewed files, despite both being in the agent's mandatory reading list.
- Error response uses `request_id`; audit/history uses `correlation_id`; standardize whether these are the same ID and response/header names.
- `PATCH /reports/{id}` describes moderator correction fields, but no separate moderator endpoint or allowed correction field list is defined.
- `GET /reports/{id}/photo` and evidence stream endpoints need explicit cache headers/content disposition and authorization cases.
- “Strip EXIF/re-encode when feasible” and “store session token hash if feasible” are non-deterministic requirements. Decide whether mandatory or not included in v1.
- “React/API integration (where test tooling permits)” weakens test requirements; select a test setup and required integration test scope.
- “Use bounded candidate counts if necessary” could alter matching correctness. No candidate cap is currently frozen; do not add one without owner approval and an explicit deterministic rule.
- Retention requires scheduled cleanup, but no scheduler/CLI execution mechanism or run frequency is defined. Keep within selected stack; no Redis/Kafka.
- `activity_logs` retention says 365 days, but report/claim status history is retained with workflow records. Exact cleanup/deletion rules and FK behavior need to be documented.
- Moderator CLI create/update behavior needs precise semantics: does invoking it update an existing moderator, reset password, or refuse if user exists? Current wording “creates/updates” is ambiguous.
- The frozen docs require exact implementation but do not define frontend design tokens, accessibility baseline, or responsive breakpoints. These are lower priority than backend/security contracts, but agent choices should be explicitly permitted or a UI specification should be added.

## 6. What is already sufficiently defined at design level

- Complete agreed F1–F6 boundary and major out-of-scope list.
- Stack and Azure service direction.
- Modular-monolith architecture and component responsibilities.
- Report and claim status vocabulary and most transition constraints.
- Verification versus physical recovery distinction.
- Atomic recovery and broad concurrency invariants.
- `match-v1` weights, scoring, date window, keyword Jaccard, threshold, tie-breaks, and persistence intent.
- SQL outbox concept, retries, and stale-job behavior.
- Session cookie/CSRF/CORS/security direction (though exact token/session implementation still needs closure).
- Private Blob/photo restrictions, file type/size rules, and intended retention period.
- Analytics definitions and Power BI Desktop direction.
- Explicit implementation/deployment/commit/push gates.

## 7. Recommended closure order before calling the repo “coding-agent ready”

1. Resolve C-04 through C-06 and the API state-transition contracts.
2. Produce exact API request/response schemas and error/status matrix.
3. Produce migration-ready schema specification.
4. Freeze session/cookie/CSRF details and API endpoint.
5. Freeze report visibility, immutable/editable fields, and matching field map.
6. Freeze seed/reference-data strategy and all text/date constraints.
7. Freeze reason/event enums, rate limiting, attachment cleanup, and retention execution.
8. Freeze Azure driver, deployment command, migration and Blob auth strategy.
9. Define exact analytics UI vs Power BI boundary and tests.
10. Update `CONSISTENCY_REVIEW.md`, README, and implementation handoff with the completed closure checklist.

## 8. Agent instruction

A coding agent without previous conversation must treat this audit as a list of **open implementation blockers**, not as permission to choose defaults. It may implement areas already fully specified, but must stop before making owner-impacting decisions listed above. It must not introduce new roles, services, states, or features to fill gaps.


## 9. Closure pass status (2026-11-05)

The specification-closure pass created `docs/IMPLEMENTATION_CONTRACTS.md` and incorporated the following resolutions into the governing documents:

- C-04 moderator claim submission: explicitly prohibited.
- C-05 report photo: report creation and photo upload are separate; upload failure does not roll back report creation; replacement requires delete then upload.
- C-06 claim decision endpoints: PENDING rejection and VERIFIED revocation have separate endpoints.
- H-01/H-02 API response/error/pagination contracts: specified in Implementation Contracts.
- H-03 schema implementation types/constraints and SQL Server mapping: specified; coding agent must implement migration constraints/indexes exactly.
- H-04 seed strategy: operator-provided campus JSON config; no ADMIN role or public reference-data admin UI.
- H-05/H-06 visibility and validation: field-level policy and text/date validation specified.
- H-07/H-08 reason/event codes and VERIFIED revocation history: specified.
- H-09 sessions/CSRF: cookie name, secret hashing, CSRF token hashing, token route, origin, expiry, and revocation specified.
- H-10 rate limiting: SQL-backed thresholds and keying specified; no Redis.
- H-11 retention: purge scheduling/reopen/void/delete-failure behavior specified.
- H-12 DEAD matching jobs: operator CLI; no ADMIN role.
- H-13/H-14 match persistence/dismissal and matching-relevant fields: specified.
- H-15 competing claim rejection metadata: system actor/reason/history behavior specified.
- H-16 Azure SQL driver, Blob managed identity, App Service startup and migration sequencing: specified. Azure quota, domain and deployment availability remain factual portal checks.
- H-17 in-app moderator dashboard and Power BI Desktop are both required.
- H-18 CSRF route is explicitly defined.

**Interpretation:** This file remains the historical record of the initial audit findings. Its original “open gaps” sections describe the pre-closure state and must not be read as current unresolved issues. Implementation Contracts is now the normative closure source. Final scan completed: no broken local Markdown links found; `config/campus.example.json` parses and all location zone references resolve; stale pre-closure wording was corrected in governing documents. The coding-agent baseline is now specification-ready, subject to implementation-time verification of Azure account/domain availability and actual CI/runtime behavior.
