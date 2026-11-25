# FindMyThing — Instructions for the Next Agent

Welcome to **FindMyThing — Secure Campus Lost & Found & Item Recovery Platform**.

This guide is your direct, actionable entry point. Follow these instructions step-by-step to immediately resume productive implementation without wasting tokens or re-inventing existing architecture.

---

## 1. What FindMyThing Is

FindMyThing is a campus lost-and-found recovery platform engineered with strict security, auditability, and data integrity guarantees:
- **Scoring Engine:** Deterministic rule-based scoring (`match-v1`), weighted by category (40%), location hierarchy (25%), date decay (25%), and tokenized keyword overlap (10%). Matches above 50 points are generated and persisted via an asynchronous SQL outbox pattern.
- **Security & Integrity:** Argon2id password hashing, opaque session tokens with 12h absolute expiry, CSRF tokens, exact Origin verification, strict metadata allowlists on audit logs, and SQL Server triggers for immutable report status history.
- **Multi-Party Lifecycle:** Separate reporting for Lost and Found items, multi-claimant competition on Found items, mandatory moderator verification notes, supervised physical handovers with OTP/verification codes, and recovery void auditing.
- **Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, Microsoft SQL Server 2022, React + TypeScript + Vite frontend (to be created), Azure Blob Storage / local disk storage adapter.

---

## 2. Authoritative Specifications & Reading Order

Do NOT invent features or alter frozen architectural decisions. Read the documentation in `docs/` in this exact order:

1. [docs/TECH_STACK.md](file:///C:/Users/ASUS/Desktop/FindMyThing/docs/TECH_STACK.md) — Languages, libraries, versions, and Azure targets.
2. [docs/ARCHITECTURE.md](file:///C:/Users/ASUS/Desktop/FindMyThing/docs/ARCHITECTURE.md) — System topology, component boundaries, and security boundaries.
3. [docs/BLUEPRINT.md](file:///C:/Users/ASUS/Desktop/FindMyThing/docs/BLUEPRINT.md) — End-to-end user journeys, state machines, business rules.
4. [docs/IMPLEMENTATION_CONTRACTS.md](file:///C:/Users/ASUS/Desktop/FindMyThing/docs/IMPLEMENTATION_CONTRACTS.md) — **The governing contract** for all API routes, schemas, database tables, and error codes.
5. [docs/IMPLEMENTATION_NOTES.md](file:///C:/Users/ASUS/Desktop/FindMyThing/docs/IMPLEMENTATION_NOTES.md) — Catalog of already resolved specification edge cases (e.g. N-001 SQL Server filtered unique index resolution).
6. [handoff/STATUS.md](file:///C:/Users/ASUS/Desktop/FindMyThing/handoff/STATUS.md) — Current state of code and test results.
7. [handoff/IMPLEMENTATION_PLAN.md](file:///C:/Users/ASUS/Desktop/FindMyThing/handoff/IMPLEMENTATION_PLAN.md) — Prioritized backlog of remaining tasks.

---

## 3. Current Implementation Status Summary

- **Phase 1 stabilization complete and verified (2026-11-11):** Ruff clean, MyPy clean (35 files), 117/117 pytest passing against real SQL Server 2022 (143 s), `match-v1` verified against the frozen spec (40/25/25/10, threshold 50).
- **Implemented and tested:** models, Alembic 0001, Auth, Reports core lifecycle, Matches and worker, Claims and Recovery core, typed `require()` / `affected_rows()` helpers.
- **Implemented but NOT wired, NOT tested:** `services/images.py` (`process_image`) and `services/blobstore.py` have no callers; `services/retention.py` only schedules purges.
- **UPDATE 2026-11-14:** report photo and claim evidence are now implemented, wired and verified (207 passed in full suite); the "not wired" and "MISSING" photo/evidence statements here are obsolete.
- **Required by the contract but MISSING (backend):** ~~report photo routes, claim evidence routes~~ (done), ~~`GET /api/moderation/analytics/summary`, `GET /api/moderation/activity`~~ (done 2026-11-14, Task 2.1; 244 tests passing), ~~`app/cli.py` (4 commands), retention purge executor~~ (done 2026-11-15, Task 2.2; 353 tests passing).
- **Not started:** frontend (`frontend/` does not exist), Azure Bicep and CI, Power BI.
- **Environment:** Docker Desktop must be running; start the DB with `docker start findmything-sql` (port 14333). It has no volumes: never `docker rm` it.
- **Git:** working tree has uncommitted changes (10 modified files, new `persistence/results.py`, `handoff/`). Do not commit or push without explicit user authorization.

---

## 4. Ground Rules & Constraints

1. **Git & Deployment Safety:**
   - **Do NOT commit or push** without explicit user instruction.
   - **Do NOT provision Azure cloud resources** or incur costs.
   - **Preserve existing documentation and codebase integrity.**
2. **Spec Precedence:**
   - [docs/IMPLEMENTATION_CONTRACTS.md](file:///C:/Users/ASUS/Desktop/FindMyThing/docs/IMPLEMENTATION_CONTRACTS.md) governs all implementation details.
   - Do not change API route contracts or response envelopes (`error.code`, `error.message`, `error.field_errors`).
3. **Database Rules:**
   - Real SQL Server 2022 only. No SQLite substitution in integration tests.
   - All locks must follow the deterministic lock order (lowercase UUID strings) established in [backend/app/services/locking.py](file:///C:/Users/ASUS/Desktop/FindMyThing/backend/app/services/locking.py).

---

## 5. EXACT NEXT TASK FOR INCOMING AGENT

### UPDATE 2026-11-26 (latest; READ THIS FIRST)
ODBC risk RESOLVED (STATUS.md 1H): the API deploys to App Service as a custom container from a PUBLIC GHCR image built from `backend/Dockerfile` by `.github/workflows/publish-image.yml` (GITHUB_TOKEN only, no secrets, no Azure access). Bicep takes a `containerImage` parameter (placeholder in `main.bicepparam`). Locally verified: ODBC Driver 18 in image, non-root `appuser`, production-mode start with `/home/site/campus/campus.json`, `/api/health` 200 without a database. NOT verified against Azure/GitHub: the publish workflow run, anonymous GHCR pull, managed-identity SQL/Blob, `/home` mount permissions. Owner steps before deploy: push, run the publish workflow, make the GHCR package public, pin the `sha-` tag, real origins and Entra admin object ID, portal quota checks, then post-deploy SQL identity user + Alembic migration + `campus.json` upload + SWA deploy + custom domains. Do NOT deploy or commit without explicit owner approval. Phase 5 still not started. (The "ODBC startup script vs container" decision in the entry below is closed.)

### UPDATE 2026-11-26 (later; infra review done; READ THIS FIRST)
Infra review finished (STATUS.md 1G): one fix (`main.bicepparam` pins `location = 'eastasia'` because the Azure for Students region policy only allows eastasia, koreacentral, malaysiawest, austriaeast, uaenorth), read-only `what-if` exit 0, nothing deployed. BEFORE any real deploy the owner must decide: (1) how App Service gets ODBC Driver 18 (startup script vs custom container from `backend/Dockerfile`); (2) real Entra admin object ID and custom-domain origins; (3) post-deploy steps (SQL identity user, migrations, campus.json). Do not deploy without explicit owner approval. Phase 5 still not started.

### UPDATE 2026-11-26 (READ THIS FIRST; overrides everything below)
Phase 4 (Azure Infrastructure & CI scaffolding) is **COMPLETE and VERIFIED locally** (details and exit codes: STATUS.md section 1F). Bicep build/build-params/lint exit 0; backend ruff/mypy/pytest (353 passed) exit 0; frontend lint/typecheck/test/build exit 0; both Docker images build and pass smoke tests. Nothing was deployed, provisioned, committed or pushed.

**NEXT TASK: Phase 5 - Power BI Analytics Integration & Handover** (`handoff/IMPLEMENTATION_PLAN.md`, Task 5.1+). Do not start it without the owner's go-ahead on scope. Owner decisions still pending: (1) whether to commit the large uncommitted tree; (2) whether to add `docker-compose.yml` (listed in the plan, not built); (3) a real Azure `what-if`/deploy needs an owner-provided subscription; (4) the CI workflow has never run on GitHub.
Environment gotchas: shell exports `NODE_ENV=production` (use `$env:NODE_ENV='development'` and `npm ci --include=dev` locally); never write config files with PowerShell `Out-File`/`Set-Content -Encoding UTF8` on Windows PowerShell 5.1 (adds a BOM); Docker BuildKit can fail transiently, so retry once; never `docker rm` `findmything-sql`.

### (Superseded) UPDATE 2026-11-25 (READ THIS FIRST; overrides previous task notes)
Phase 3 (Frontend Implementation) is **COMPLETE and VERIFIED**:
- All student workflows: registration, sign in, report creation with photo, report search/filter, report editing (`PATCH /reports/{id}`), withdrawal, matches and recalculation trigger, claim submission (with optional link to own lost report), evidence photo management (upload/delete), claim cancellation.
- All moderator workflows: claims review queue (`/moderator`), claim verification, info request, rejection with mandatory reason codes, in-person recovery handover completion, recovery voiding, evidence removal, report moderation (close with reasons, reopen, field corrections with decision notes), analytics summary dashboard, and activity log audit feed.
- Verification passes:
  - `npm run lint`: exit 0
  - `npx tsc -b`: exit 0
  - `npm test -- --run`: 40 tests passed, exit 0
  - `npm run build`: production bundle generated in 869ms, exit 0

**NEXT TASK: Phase 4 — Azure Infrastructure & CI/CD Scaffolding** (`handoff/IMPLEMENTATION_PLAN.md` Phase 4, Task 4.1 Bicep templates & Task 4.2 GitHub Actions / Dockerfiles).
Remember: do NOT provision live Azure resources or deploy without explicit user authorization. Build and validate infrastructure templates and CI workflows locally.

### (Superseded) UPDATE 2026-11-14 (later session) - Task 2.1 complete, Task 2.2 was next
Task 2.1 is COMPLETE and VERIFIED against real SQL Server: `GET /api/moderation/analytics/summary` and `GET /api/moderation/activity` implemented (`app/api/routes_analytics.py`, `app/services/analytics.py`, mounted in `app/main.py`; tests `tests/test_analytics_api.py` 24 + `tests/test_activity_api.py` 13). Results: focused 37 passed, full suite **244 passed**, `ruff check app tests` clean, `mypy app` clean (38 files). Definitions, privacy rules and files are in STATUS.md section 1C. No migration, no view change, photo/evidence untouched.

**NEXT TASK: Task 2.2 — Administrative CLI and Retention Executor.** Create `backend/app/cli.py` (run as `python -m app.cli`) with `create-moderator` (interactive; refuses an existing email; never updates role/password), `seed-reference-data --config <path>` (deterministic UUIDs; never renames report-linked rows), `cleanup-retention` (idempotent executor: 90-day attachment/evidence purge Blob-first then mark metadata deleted, Blob 404 = success, 24 h orphan Blob cleanup, 365-day `activity_logs` purge, audit outcome only; `services/retention.py` currently only schedules `purge_after_utc`), and `matching-jobs list --status DEAD` / `matching-jobs retry <job_id>` (actor logged as `OPERATOR`, `actor_user_id` NULL). Contract: `docs/IMPLEMENTATION_CONTRACTS.md` sections 10, 11, 16 (lines ~162-175, 220-227). Add retention and CLI tests against real SQL Server and `LocalBlobStore`. Gate: ruff/mypy clean, full `pytest -v` passes (baseline now 244), `python -m app.cli --help` and each subcommand `--help` work. Then Phase 3 (frontend).

Open items for the owner (non-blocking, see STATUS.md 1C "Additions to confirm"): two additive analytics keys (`report_status_counts`, `recovery_rate_basis`) and three optional activity filters (`event_type`, `outcome`, `target_type`) go beyond contract 4.5 as written.

Baseline before starting (expected: clean, clean, 244 passed):
```powershell
cd C:\Users\ASUS\Desktop\FindMyThing\backend
.\.venv\Scripts\ruff check app tests
.\.venv\Scripts\mypy app
.\.venv\Scripts\pytest -q   # ~6.5 min; run ONE pytest process at a time, log to a file and poll it
```
SQL Server readiness: pyodbc connect with 15 s timeout (`docker ps` can hang). Never `docker rm` the container, never use SQLite, do not commit/push.

### (Superseded) UPDATE 2026-11-14 (earlier session) — Task 2.1 was the next task then
Claim evidence and report photo are COMPLETE and VERIFIED against real SQL Server: claim-evidence 37 passed, report-photo 53 passed, full suite 207 passed, `ruff check app tests` clean, `mypy app` clean (36 files). Details: STATUS.md section 1B. Task 2.0 (including the old 2.0A/2.0B/2.0C steps) is closed; ignore the 2026-11-12 gate and "do not start claim evidence" text below.

**NEXT TASK: Task 2.1 — Moderator Analytics and Activity Routes.** Implement `GET /api/moderation/analytics/summary` and `GET /api/moderation/activity` per `docs/IMPLEMENTATION_CONTRACTS.md` lines 99-100 and section 22 (metric semantics): new `app/api/routes_analytics.py` + `app/services/analytics.py`, mount in `app/main.py`. Moderator only; unavailable rates/times are `null` not 0; default window last 90 days, max range 366 days, inclusive dates, campus-timezone boundaries; activity metadata allowlisted/sanitized, never claim statements/evidence; newest first with `{items,page,page_size,total}`. Add API tests against real SQL Server. After 2.1: Task 2.2 (CLI + retention executor), then Phase 3 frontend.

Baseline before starting (expected: clean, clean, 207 passed):
```powershell
cd C:\Users\ASUS\Desktop\FindMyThing\backend
.\.venv\Scripts\ruff check app tests
.\.venv\Scripts\mypy app
.\.venv\Scripts\pytest -q   # ~7.5 min; run ONE pytest process at a time, log to a file
```
SQL Server readiness: use a pyodbc connect with 15 s timeout (`docker ps` can hang while SQL Server is fine). Never `docker rm` the container, never use SQLite, do not commit/push.

### (Historical) UPDATE 2026-11-12 — obsolete, kept for context
Report-photo upload/get/delete is IMPLEMENTED (`app/services/attachments.py`, routes in `routes_reports.py`, `images.py` hardening) with 28 real tests in `backend/tests/test_report_photo_api.py` (+ `tests/image_fixtures.py`). Ruff and mypy are clean (36 files). The 28 tests have NEVER RUN against SQL Server: Docker engine/SQL Server was not responding on 2026-11-12 (port 14333 open, prelogin timeout; `docker ps` hangs). Do not delete/recreate the container, do not use SQLite.

**Step 0 (gate, do first):** get `findmything-sql` answering (`docker start findmything-sql`, wait for "SQL Server is now ready" in `docker logs`), then:
```powershell
cd C:\Users\ASUS\Desktop\FindMyThing\backend
.\.venv\Scripts\pytest -v tests/test_report_photo_api.py
```
Fix any failures (suspects listed in STATUS.md section 1A "Remaining defects"), then run `ruff check app tests`, `mypy app`, full `pytest -v` (baseline was 117 passed + the 28 new).

**Then: Task 2.0B — Authorized Report Photo Retrieval.** GET already exists; 2.0B = verify/harden it against contract lines 39-40, 72: owner and moderator access, non-owner student only for ACTIVE/RESOLVED reports (404 for WITHDRAWN/CLOSED), no data for deactivated users, headers `Cache-Control: private, no-store`, `X-Content-Type-Options: nosniff`, safe inline filename, `has_photo` flag in report DTOs (contract line 249), missing-Blob 404. Add the missing negative tests (non-owner on withdrawn/closed report, anonymous GET 401, moderator GET). Do NOT start claim evidence routes until 2.0B passes; the evidence service functions already in `attachments.py` are unrouted and untested.

(Original Phase 2 text follows; the report-photo portion of item 1 is done.)

Your task is **Phase 2: complete the backend contract surface.** Do NOT start the frontend until Phase 2 passes its gate; the frontend depends on the photo, evidence and analytics endpoints.

Confirm the baseline first (needs the SQL Server container running):
```powershell
cd C:\Users\ASUS\Desktop\FindMyThing\backend
.\.venv\Scripts\ruff check app tests
.\.venv\Scripts\mypy app
.\.venv\Scripts\pytest -q
```
Expected: clean, clean, 117 passed.

Then implement, in this order, following `docs/IMPLEMENTATION_CONTRACTS.md` (it governs; do not copy the old plan wording):

1. **Task 2.0 - Photo and evidence endpoints.** Wire `process_image()` and `get_blob_store()` into: `POST/GET/DELETE /api/reports/{id}/photo`; `POST /api/claims/{id}/evidence`, `GET /api/claims/{id}/evidence/{evidence_id}`, claimant `DELETE`, moderator `DELETE /api/moderation/claims/{id}/evidence/{evidence_id}`. Contract lines 72, 95, 157, 165, 307, 311, 370. Enforce 5,000,000-byte limit before Blob upload and after re-encode, one report photo, three evidence images total under the claim lock, EXIF stripping, `Cache-Control: private, no-store` and `nosniff` on GET, audit every moderator evidence access, 503 (metadata retained) on Blob delete failure. Add API tests with real image fixtures (including animated, oversized, corrupt, wrong-type) using `LocalBlobStore`.
2. **Task 2.1 - Analytics and activity feed.** `routes_analytics.py` and `services/analytics.py`; response shapes exactly as contract lines 99-100 (unavailable rates/times are `null`, never 0; default window 90 days; max 366; campus-timezone boundaries; sanitized metadata; never claim statements or evidence).
3. **Task 2.2 - CLI.** `backend/app/cli.py` with `create-moderator` (interactive, refuses existing email), `seed-reference-data` (deterministic UUIDs, never renames report-linked rows), `cleanup-retention` (idempotent; Blob first then mark metadata deleted, Blob 404 = success, 24 h orphan cleanup, purge `activity_logs` older than 365 days, audit outcome only), `matching-jobs list --status DEAD` and `matching-jobs retry <job_id>` (actor logged as `OPERATOR`, `actor_user_id` NULL). Also add retention tests.

**Gate for Phase 2 (all must hold, with real output reported):** `ruff check app tests` exit 0; `mypy app` exit 0 with no new `Any`/ignores; full `pytest -v` passes against SQL Server with the new tests; `python -m app.cli --help` and each subcommand `--help` work. Then update the three handoff files and set the next task to **Phase 3: full frontend implementation** per `handoff/IMPLEMENTATION_PLAN.md`.

Never change frozen rules (matching weights 40/25/25/10, threshold 50, 30-day window, `match-v1`).

---

## 6. Handoff Maintenance Protocol

After completing any significant implementation milestone:
1. Update `handoff/STATUS.md` with newly implemented files, verified test results, and any new edge cases discovered.
2. Check off completed items in `handoff/IMPLEMENTATION_PLAN.md` and refine acceptance criteria for downstream items.
3. Update `handoff/NEXT_AGENT.md` with the new exact next task for the subsequent session.
