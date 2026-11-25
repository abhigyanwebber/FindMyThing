# FindMyThing — Implementation Plan & Remaining Work Checklist

**Authoritative Spec Reference:** `docs/BLUEPRINT.md`, `docs/IMPLEMENTATION_CONTRACTS.md`, `docs/TECH_STACK.md`  
**Execution Ordering:** Strictly dependency-ordered.

---

## Phase 1: Backend Polish, Static Quality & Test Validation

- [x] **Task 1.1: Resolve Ruff Linting Violations** (DONE 2026-11-11: `ruff check app tests` exit 0)
  - **Priority:** High (Prerequisite for clean CI)
  - **Dependencies:** None
  - **Files:**
    - [backend/app/services/blobstore.py](file:///C:/Users/ASUS/Desktop/FindMyThing/backend/app/services/blobstore.py#L103)
    - [backend/app/services/claims.py](file:///C:/Users/ASUS/Desktop/FindMyThing/backend/app/services/claims.py#L41)
  - **Expected Outcome:** Line lengths broken down to <= 140 chars.
  - **Acceptance Criteria:** `ruff check app tests` exits code 0.
  - **Verification:** Run `ruff check app tests`.

- [x] **Task 1.2: Resolve Mypy Type Checking Errors** (DONE 2026-11-11: 35 files, 0 errors; `require()` and `affected_rows()` added)
  - **Priority:** High
  - **Dependencies:** Task 1.1
  - **Files:**
    - [backend/app/services/images.py](file:///C:/Users/ASUS/Desktop/FindMyThing/backend/app/services/images.py)
    - [backend/app/core/ratelimit.py](file:///C:/Users/ASUS/Desktop/FindMyThing/backend/app/core/ratelimit.py)
    - [backend/app/services/matching_state.py](file:///C:/Users/ASUS/Desktop/FindMyThing/backend/app/services/matching_state.py)
    - [backend/app/services/matching_worker.py](file:///C:/Users/ASUS/Desktop/FindMyThing/backend/app/services/matching_worker.py)
    - [backend/app/services/matches.py](file:///C:/Users/ASUS/Desktop/FindMyThing/backend/app/services/matches.py)
    - [backend/app/services/claims.py](file:///C:/Users/ASUS/Desktop/FindMyThing/backend/app/services/claims.py)
    - [backend/app/api/routes_auth.py](file:///C:/Users/ASUS/Desktop/FindMyThing/backend/app/api/routes_auth.py)
  - **Expected Outcome:** Proper explicit typing, handling optional `None` cases, casting SQLAlchemy results.
  - **Acceptance Criteria:** `mypy app` passes with 0 errors.
  - **Verification:** Run `mypy app`.

- [x] **Task 1.3: Validate Full Pytest Integration Suite against SQL Server** (DONE 2026-11-11: 117 passed, 0 skipped, real SQL Server 2022)
  - **Priority:** High
  - **Dependencies:** Docker container restart / fresh SQL Server instance.
  - **Files:** [backend/tests/](file:///C:/Users/ASUS/Desktop/FindMyThing/backend/tests/)
  - **Expected Outcome:** All 117 backend tests pass without hangs or deadlocks.
  - **Acceptance Criteria:** `pytest` exits code 0 with 117 passed tests.
  - **Verification:** Run `pytest`.

---

## Phase 2: Remaining Backend Contract Surface (Photo/Evidence, Analytics, CLI, Retention)

**Status:** COMPLETE (2026-11-15). Tasks 2.0, 2.1 and 2.2 are done and verified (full suite 353 passed); NEXT is Phase 3 - Complete Frontend Implementation. Added after the 2026-11-11 route/CLI inventory showed these contract-required items missing. `docs/IMPLEMENTATION_CONTRACTS.md` governs wherever this plan differs.

- [x] **Task 2.0: Implement Report Photo and Claim Evidence Endpoints** (DONE and VERIFIED 2026-11-14: claim evidence 37 passed, report photo 53 passed, full suite 207 passed, ruff and mypy clean; see STATUS.md 1B. Task 2.0B hardening audit of photo GET/`has_photo` not separately re-audited.)
  - **Superseded history (2026-11-12 note, now obsolete):** REPORT PHOTO half implemented (POST/GET/DELETE `/api/reports/{id}/photo`, `services/attachments.py`, `images.py` 415 + metadata hardening, 28 tests in `tests/test_report_photo_api.py`). Ruff and mypy clean. Photo tests NOT YET RUN against SQL Server (Docker/SQL Server unresponsive). Claim-evidence: service functions exist in `attachments.py` but NO routes and NO tests (still TODO).
  - **Task 2.0A (gate):** start `findmything-sql`, run `pytest -v tests/test_report_photo_api.py`, fix failures, run ruff/mypy/full pytest.
  - **Task 2.0B (next after 2.0A): Authorized Report Photo Retrieval** - verify/harden existing GET against contract lines 39-40, 72 (non-owner only ACTIVE/RESOLVED, headers, `has_photo`, 401/404 negatives, moderator access) and add missing tests.
  - **Task 2.0C:** claim evidence routes + tests (after 2.0B).
  - **Priority:** High (blocks the frontend report and claim forms)
  - **Dependencies:** Phase 1 (done)
  - **Files:** `backend/app/api/routes_reports.py`, `backend/app/api/routes_claims.py`, `backend/app/services/images.py`, `backend/app/services/blobstore.py`, `backend/app/services/retention.py`, new tests
  - **Expected Outcome:** `POST/GET/DELETE /api/reports/{id}/photo`; `POST /api/claims/{id}/evidence`, `GET`/`DELETE /api/claims/{id}/evidence/{evidence_id}`; moderator `DELETE /api/moderation/claims/{id}/evidence/{evidence_id}`. Contract lines 72, 95, 157, 165, 307, 311, 370.
  - **Acceptance Criteria:** 5,000,000-byte limit enforced before upload and after re-encode; one report photo; three evidence images total under claim lock; EXIF stripped; private/no-store/nosniff headers; moderator evidence access audited; 503 and retained metadata when Blob deletion fails.
  - **Verification:** API tests with real image fixtures (valid JPEG/PNG/WebP, animated, oversized, corrupt, mismatched type) against `LocalBlobStore` and real SQL Server.

- [x] **Task 2.1: Implement Analytics & Activity Feed Endpoints** (DONE and VERIFIED 2026-11-14: focused 37 passed, full suite 244 passed, ruff clean, mypy clean 38 files; see STATUS.md 1C. No migration or view change. Two additive analytics keys and three optional activity filters are flagged in STATUS.md 1C for owner confirmation.)
  - **Contract:** response shapes exactly per `IMPLEMENTATION_CONTRACTS.md` lines 99-100; unavailable rates/times are `null`, not 0.
  - **Priority:** Medium
  - **Dependencies:** Phase 1
  - **Files (as built):**
    - `backend/app/api/routes_analytics.py` (new)
    - `backend/app/services/analytics.py` (new)
    - `backend/app/main.py` (router mount)
    - `backend/tests/test_analytics_api.py` (new, 24 tests), `backend/tests/test_activity_api.py` (new, 13 tests)
  - **Expected Outcome:** Moderator endpoints for recovery metrics, category distribution, time-to-recovery, and paginated activity feed querying `reports`/`recoveries`/`claim_status_history` (analytics) and `activity_logs` (activity). The existing views were not reused for the API (per-row rounding of `days_to_recovery`).
  - **Acceptance Criteria:** `GET /api/moderation/analytics/summary` and `GET /api/moderation/activity` return compliant envelopes accessible only to moderators. MET.
  - **Verification:** `pytest -v tests/test_analytics_api.py tests/test_activity_api.py` (37 passed) and full suite (244 passed).

- [x] **Task 2.2: Implement Management CLI Tooling** (DONE and VERIFIED 2026-11-15: `python -m app.cli` with `create-moderator`, `seed-reference-data`, `cleanup-retention`, `matching-jobs run|list|retry`; real retention executor in `services/cleanup.py`; focused 109 passed, full suite 353 passed, ruff clean, mypy clean (41 files); details in STATUS.md section 1D)
  - **Priority:** Medium
  - **Dependencies:** Phase 1
  - **Files:**
    - `backend/app/cli.py` or dedicated scripts in `scripts/`
  - **Expected Outcome:** CLI commands for:
    - `create-moderator` (interactive prompts for name/email/password per contract line 222; refuses an existing email; never updates role/password)
    - `seed-reference-data --config <path>`
    - `cleanup-retention` (idempotent retention executor: 90-day attachment/evidence purge Blob-first, 24 h orphan Blobs, 365-day `activity_logs` purge; contract lines 162-167, 224; `purge_expired_data()` does not exist yet and must be written)
    - `matching-jobs list --status DEAD` and `matching-jobs retry <job_id>` (contract line 225; actor logged as `OPERATOR`, `actor_user_id` NULL)
  - **Acceptance Criteria:** All CLI commands execute idempotently without requiring an active web server.
  - **Verification:** CLI invocations with `--help` and live test executions.

---

## Phase 3: Frontend Implementation (React + TypeScript + Vite)

**Status:** COMPLETE and VERIFIED (2026-11-25). All student and moderator flows implemented, connected to API, typechecked, linted, and covered by automated tests.

- [x] **Task 3.1: Frontend Project Scaffolding** (DONE: Vite + React 19 + TypeScript + Vitest + CSS Modules)
- [x] **Task 3.2: API Client, Auth Context & Security Integration** (DONE: `AuthProvider.tsx`, `auth-context.ts`, `client.ts`, `data.ts`, `RequireRole.tsx`)
- [x] **Task 3.3: Student Views & Workflows** (DONE: Sign In, Register, Browse & Filter Reports, Report Creation + Photo Upload, Report Detail, Edit Report, Withdraw Report, Matches & Recalculate, Submit Claim with Optional Lost Report Link, My Reports, My Claims, Claim Detail + Evidence Upload/Deletion, Cancel Claim)
- [x] **Task 3.4: Moderator Views & Workflows** (DONE: Claims Queue with Status Tabs, Claim Review Detail, Verification, Rejection with Mandatory Reason Codes, Info Request, In-Person Handover Recovery, Recovery Void, Evidence Removal, Report Moderation Close/Reopen/Correct, Analytics Dashboard, Activity Audit Feed)

---

## Phase 4: Azure Infrastructure & CI/CD Scaffolding

- [x] **Task 4.1: Bicep Infrastructure as Code Templates** (COMPLETE 2026-11-26; `az bicep build`, `build-params`, `lint` all exit 0; also contains Static Web Apps in `main.bicep`, blob role assignment in `modules/blob-role.bicep`, `main.bicepparam`. Never deployed.)
  - **Priority:** Medium
  - **Dependencies:** None
  - **Files:**
    - `infra/main.bicep`
    - `infra/modules/appservice.bicep`
    - `infra/modules/sql.bicep`
    - `infra/modules/storage.bicep`
  - **Expected Outcome:** Parametrized Bicep templates defining Azure App Service (Linux Python), Azure SQL Database Serverless, and Azure Blob Storage with private access and managed identities.
  - **Acceptance Criteria:** `az bicep build --file infra/main.bicep` compiles without errors. (NO cloud provisioning).
  - **Verification:** Bicep build / linter command.

- [x] **Task 4.2: Containerization & GitHub Actions CI/CD** (COMPLETE 2026-11-26: `backend/Dockerfile`, `frontend/Dockerfile`, `frontend/nginx.conf`, `.dockerignore`, `frontend/.dockerignore`, `.github/workflows/ci.yml`; both images built and smoke-tested locally. API hosting resolved 2026-11-26: App Service custom container from a PUBLIC GHCR image published by `.github/workflows/publish-image.yml` (see STATUS.md 1H; not verified against Azure). `docker-compose.yml` was NOT created: it was not in the Phase 4 required deliverables for this session; add only if the owner asks.)
  - **Priority:** Medium
  - **Dependencies:** Task 1.1, Task 3.1
  - **Files:**
    - `backend/Dockerfile`
    - `frontend/Dockerfile`
    - `docker-compose.yml` (production-like compose)
    - `.github/workflows/ci.yml`
  - **Expected Outcome:** Clean Docker multi-stage builds and automated CI workflow running Ruff, Mypy, pytest, and frontend build.
  - **Acceptance Criteria:** CI workflow triggers on push/PR.
  - **Verification:** Local Docker build tests.

---

## Phase 5: Power BI Analytics Integration & Handover

- [ ] **Task 5.1: Power BI DirectQuery Semantic Definition**
  - **Priority:** Low
  - **Dependencies:** Phase 2
  - **Files:**
    - `docs/analytics/POWER_BI_INTEGRATION.md`
    - `scripts/export_powerbi_schema.sql`
  - **Expected Outcome:** DirectQuery connection strings, SQL view schema documentation, and DAX metric specifications targeting `vw_recovery_analytics` and `vw_claim_transition_analytics`.
  - **Acceptance Criteria:** Detailed setup guide for connecting Power BI Desktop to Azure SQL via Read-Only service principal.
  - **Verification:** Documentation review against Azure SQL security model.
