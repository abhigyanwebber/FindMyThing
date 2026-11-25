# FindMyThing — Implementation Status & Audit Snapshot

**Snapshot Timestamp:** 2026-11-25  
**Repository Path:** `C:\Users\ASUS\Desktop\FindMyThing`  
**Git Branch:** `main` (commit `d62c658 "implementation milestone"`)  
**Current Phase:** Phase 1 (Backend static quality & tests) COMPLETE. Phase 2 (Backend contract surface & CLI) COMPLETE. Phase 3 (Frontend React + TypeScript + Vite SPA, Student & Moderator Workflows) COMPLETE and VERIFIED. Phase 4 (Azure Infrastructure & CI) COMPLETE and verified locally 2026-11-26 (see 1F; not deployed).

---

## 1. Executive Summary

FindMyThing is a campus-focused, security-first Lost & Found and Item Recovery platform with:
- Pure rule-based deterministic scoring (`match-v1`).
- Strict audit trails and report status history triggers.
- Multi-party claim verification and supervised recovery workflows.
- SQL Server 2022 backend with FastAPI, SQLAlchemy 2, and Alembic migrations.
- Modern React + TypeScript + Vite accessible frontend SPA with CSS Modules, strict role routing, and full API integration.

## 1H. Session 2026-11-26 (latest) - ODBC deployment decision RESOLVED: App Service custom container from a public GHCR image (NOTHING deployed)

**Decision:** run the API on Linux App Service as a **custom container** built from the existing `backend/Dockerfile` and pulled from a **public GitHub Container Registry image**. Rejected: built-in Python runtime plus a startup script that apt-installs `msodbcsql18` (re-runs on every restart, adds minutes to cold start, depends on Microsoft's apt repo being reachable at boot, and is not testable locally). The image already installs the driver, builds, runs non-root and was smoke-tested, so it is the reproducible path. GHCR avoids an Azure Container Registry (extra cost); Microsoft docs state that for a public registry no credentials are needed and only the image name is set, so no `DOCKER_REGISTRY_SERVER_*` settings and no secrets exist. Docs also say custom containers only mount `/home` when `WEBSITES_ENABLE_APP_SERVICE_STORAGE=true`, and need `WEBSITES_PORT` for a non-80 port.

Files changed: `infra/modules/appservice.bicep` (new required `containerImage` param; `linuxFxVersion: DOCKER|<image>`; removed `appCommandLine`, `pythonVersion`, `SCM_DO_BUILD_DURING_DEPLOYMENT`; added `WEBSITES_ENABLE_APP_SERVICE_STORAGE=true`; kept `WEBSITES_PORT=8000`, managed identity, health check `/api/health`, absolute `CAMPUS_CONFIG_PATH`), `infra/main.bicep` (passes `containerImage`), `infra/main.bicepparam` (placeholder `ghcr.io/abhigyanwebber/findmything-api:main`), `backend/Dockerfile` (added `org.opencontainers.image.source` label only), NEW `.github/workflows/publish-image.yml` (push to main touching backend, or manual; builds, smoke-tests ODBC/health/non-root, pushes `:sha-<12>` and `:main`; uses only the built-in `GITHUB_TOKEN`, `packages: write`, no secrets, no Azure access, no deploy). `ci.yml` unchanged (still no deploy).

Required GitHub configuration (cannot be done by a workflow): after the FIRST successful publish run, set the package `findmything-api` visibility to **Public** (new packages default to private and App Service has no pull credentials). Image names must be lowercase. Pin the sha tag in the deployment parameter, not `:main`.

Validation executed this session (exit codes): `az bicep build` 0; `build-params` 0; `lint` 0. `az deployment group what-if -g rscgrp-01` (read-only, authenticated student session) exit 0, same Create list as before plus role assignment `Unsupported` (output not evaluable pre-deploy); it does not pull or run the image. Backend: `ruff` 0, `mypy` 0 (41 files), `pytest` 0 (353 passed, 193 s). Frontend: `npm ci --include=dev` 0, lint 0, typecheck 0, test 0, build 0. Docker: backend image build 0 (with the new label), frontend image build 0. Image checks: `odbcinst -q -d` exit 0 shows `[ODBC Driver 18 for SQL Server]`; `pyodbc.drivers()` lists it. Production-mode container (`APP_ENV=production`, https origins, `ActiveDirectoryMsi` DATABASE_URL pointing to a non-existent server, campus.json mounted read-only at `/home/site/campus/campus.json`, `CAMPUS_CONFIG_PATH` set to that absolute path): started cleanly, `GET /api/health` 200 `{"status":"ok"}` with no database reachable, Docker health `healthy`, process `uid=10001(appuser)`, config file readable by that user. Frontend container: `/` 200 and `/some/spa/route` 200.

NOT verified (cannot be without Azure/GitHub): the CI publish workflow has never run; GHCR anonymous pull by App Service is configured per Microsoft docs but untested; managed-identity token acquisition to SQL/Blob from inside the container; read access of `appuser` to the real Azure Files `/home` mount (tested only with a local bind mount); that the `/home` mount survives restarts. The deployment path is therefore configured and locally tested, NOT verified against Azure.

Remaining prerequisites before deploy: push the repo and run `publish-image.yml`, make the package public, copy the `sha-` tag into `containerImage`; real `frontendOrigin`/`apiPublicOrigin`/Entra admin object ID; portal checks for B1 quota and SQL serverless in an allowed region (default eastasia); post-deploy: create SQL user for the site identity (`CREATE USER [<apiSiteName>] FROM EXTERNAL PROVIDER` + minimum roles), run Alembic migrations once (image contains `alembic.ini`/`migrations`; run from a machine/Cloud Shell with an Entra login or `az webapp ssh`), upload `campus.json` to `/home/site/campus/`, deploy SWA `dist/` built with the real `VITE_API_BASE_URL`, configure custom domains, create the first moderator via `python -m app.cli`. Deploy command (NOT EXECUTED): `az deployment group create --resource-group <rg> --template-file infra/main.bicep --parameters infra/main.bicepparam --parameters containerImage=ghcr.io/<owner>/findmything-api:sha-<12chars>`. Run the same with `what-if` first.

No Azure resources created or modified; no git commit or push.

---

## 1G. Session 2026-11-26 (later) - Phase 4 Infrastructure Review & Deployment Readiness (NOTHING deployed)

NOTE: the "ODBC Driver 18 on App Service" open risk below is now RESOLVED by section 1H (custom container). The `SCM_DO_BUILD_DURING_DEPLOYMENT` finding no longer applies.

Reviewed in full: `infra/main.bicep`, `main.bicepparam`, `modules/{sql,storage,blob-role,appservice}.bicep`, `frontend/public/staticwebapp.config.json`, `backend/Dockerfile`, `frontend/Dockerfile`, `frontend/nginx.conf`, `.github/workflows/ci.yml`, `.gitignore`, `.dockerignore`, backend `config.py` env aliases and `blobstore.py` auth.

Fix made (one): `infra/main.bicepparam` now pins `param location = 'eastasia'`. Reason: the subscription (Azure for Students) has policy "Allowed resource deployment regions" = eastasia, koreacentral, malaysiawest, austriaeast, uaenorth. The existing RG `rscgrp-01` is in centralindia, and the template defaulted to the RG region, so `what-if` failed with `RequestDisallowedByAzure` for the storage account, SQL server and database. No test applies (IaC only).

Verified correct (by reading the templates): SQL is Entra-only (`azureADOnlyAuthentication: true`, no SQL login/password anywhere), TLS 1.2, serverless `GP_S_Gen5` 1 vCore, min 0.5, auto-pause 60 min. Storage: no public blob access, no shared-key auth, container `publicAccess: None`, TLS 1.2, soft delete 7 d. Role: Storage Blob Data Contributor scoped to the one container, `principalType: ServicePrincipal`, principal from the App Service output. App Service: system-assigned identity, `httpsOnly`, FTPS/basic FTP disabled, Always On, `healthCheckPath /api/health` (route exists; does not touch the DB so it does not wake auto-pause), `WEBSITES_PORT 8000` matches the uvicorn command, `CAMPUS_CONFIG_PATH` absolute, `DATABASE_URL` uses `ActiveDirectoryMsi;Encrypt=yes;TrustServerCertificate=no` (no secret). All app setting names match `Settings` aliases. Outputs contain no secrets. SWA is Free, no repo link, has SPA fallback config; `VITE_API_BASE_URL` is a build-time public value only. Docker/CI: non-root, installs from `requirements.txt`, no Azure credentials, no deploy step, no secrets (only a throwaway CI SQL password, labelled as such). Local `.env` files are git-ignored and `.dockerignore`d.

Security findings (accepted/open, none changed):
1. SQL firewall rule `AllowAllWindowsAzureIps` (0.0.0.0) lets any Azure-hosted service, including other tenants', reach the server endpoint; protection rests on Entra-only auth. Frozen design has no VNet/private endpoint; consider restricting to App Service outbound IPs later.
2. Storage `publicNetworkAccess: Enabled`, `defaultAction: Allow`: reachable from the internet but anonymous and key access are disabled, so only Entra identities with the role can read.
3. `SCM_DO_BUILD_DURING_DEPLOYMENT=true` means Oryx builds on deploy; pinned requirements are used.

OPEN RISKS (unverified, need an owner decision or a first real deploy):
- **ODBC Driver 18 on App Service.** The Bicep uses the built-in Linux Python runtime (`PYTHON|3.12`) with a code deployment. As far as I know that image does not ship `msodbcsql18`, which `pyodbc` and the contract need ("App Service deployment must provide the compatible driver"). The tested Dockerfile installs it, but Bicep does not use the image. Options: (a) startup script that installs the driver, or (b) switch the site to a custom container using `backend/Dockerfile` (needs a registry: extra cost/resource, so it is an owner decision). Not changed here; not verifiable without Azure.
- **Managed identity SQL access is not created by Bicep.** After deploy, an Entra admin must run `CREATE USER [<apiSiteName>] FROM EXTERNAL PROVIDER;` plus minimum roles, and run Alembic migrations as a one-off step (the app does not migrate at startup).
- **Campus config** must exist at `/home/site/campus/campus.json` on the App Service share before start (operator uploads it; not in IaC).
- Custom domains on the same registrable domain for SWA and the API are mandatory (ARCHITECTURE A-01) and are not in Bicep; `frontendOrigin`/`apiPublicOrigin` placeholders (`app.example.edu`, `api.example.edu`) must be replaced.
- Quotas/SKU: `what-if` does not check capacity. Portal checks needed for B1 App Service quota and Azure SQL serverless availability in the chosen allowed region (eastasia is the default; koreacentral also passed `what-if`).

Validation (executed, exit codes): `az bicep build` 0; `az bicep build-params` 0; `az bicep lint` 0. `az deployment group what-if -g rscgrp-01 ... main.bicepparam` (authenticated "Azure for Students" session, read-only): first run exit 1 (region policy, above); after the fix exit 0 listing Create for SQL server/db/firewall rule, storage account/blob service/container, plan, site, ftp policy, static site; the role assignment shows `Unsupported` (what-if cannot evaluate the principalId output before the site exists). `what-if` also ran with `location=koreacentral` (Create list returned; exit code masked by output truncation) and `eastasia` before the pin. what-if is NOT a full validation: capacity, quota, permissions and runtime behavior are untested.

Deployment readiness checklist:
1. Permissions: Owner (or Contributor + User Access Administrator) on the target RG, needed for the role assignment. Resource providers Microsoft.Web, Sql, Storage, Authorization registered.
2. Parameters to set (no secrets): `frontendOrigin`, `apiPublicOrigin` (real https origins, same registrable domain), `sqlEntraAdminLogin`, `sqlEntraAdminObjectId` (real Entra user/group object ID), `sqlEntraAdminPrincipalType`; keep `location` in the allowed list.
3. Nothing secret is required at deploy time (Entra-only SQL, managed identity Blob, no keys).
4. Command (later, with owner approval): `az deployment group create --resource-group <rg> --template-file infra/main.bicep --parameters infra/main.bicepparam`. Run `what-if` first.
5. Expected resources: SQL server + `findmything` DB + firewall rule; Storage account + `findmything-private` container; App Service plan (B1) + Linux site with system identity; role assignment; Static Web App (Free). Outputs: `apiSiteName`, `apiDefaultHostname`, `apiPrincipalId`, `sqlServerFqdn`, `sqlDatabaseName`, `storageAccountName`, `storageContainerName`, `staticWebAppName`, `staticWebAppDefaultHostname`.
6. Post-deploy manual steps: ODBC driver decision, SQL identity user + migrations, upload `campus.json`, deploy API code and SWA `dist/`, custom domains, create the first moderator via CLI.

No Azure resources were created or modified (`what-if` is read-only). No git commit or push.

---

## 1F. Session 2026-11-26 - Phase 4 Azure Infrastructure & CI Scaffolding (COMPLETE and VERIFIED locally; NOTHING deployed)

Delivered (all uncommitted): `infra/main.bicep` (includes Static Web Apps `Microsoft.Web/staticSites`), `infra/main.bicepparam`, `infra/modules/{sql,storage,appservice,blob-role}.bicep` (Azure SQL, private Blob Storage, Linux App Service with SystemAssigned identity, Blob role assignment), `backend/Dockerfile` (repo-root build context, ODBC 18, non-root user, healthcheck, installs from `backend/requirements.txt`), `backend/requirements.txt`, `backend/requirements-dev.txt`, `frontend/Dockerfile`, `frontend/nginx.conf`, `.dockerignore`, `frontend/.dockerignore`, `.github/workflows/ci.yml` (backend, frontend, infra, docker jobs), `.gitignore` additions. Only code change this session: `frontend/Dockerfile` now runs `npm ci --include=dev`. `docker-compose.yml` was not created (not a required deliverable).

Issues resolved: `nginx.conf` had NO BOM on entry (verified by byte check; all Dockerfiles, bicep, ci.yml, ignore files also BOM-free). The shell exports `NODE_ENV=production`; local frontend steps were run with `NODE_ENV=development` and `npm ci --include=dev`, and the Dockerfile is explicit about dev deps so it does not depend on the environment. A first backend `docker build` failed with a transient BuildKit error ("forwarding Ping: no such job"); an identical retry succeeded.

Results (executed this session, exit codes captured):
- `az bicep build --file infra/main.bicep`: 0. `az bicep build-params --file infra/main.bicepparam`: 0. `az bicep lint --file infra/main.bicep`: 0 (Bicep CLI 0.49.2).
- Backend: `ruff check app tests` 0; `mypy app` 0 (41 files); `pytest -q` 0, **353 passed**, 1 warning, 232 s.
- Frontend: `npm ci --include=dev` 0; `npm run lint` 0; `npm run typecheck` 0; `npm test` 0; `npm run build` 0 (with `VITE_API_BASE_URL=https://api.example.edu/api`).
- `docker build -f backend/Dockerfile -t findmything-api:local .`: 0. `docker build --build-arg VITE_API_BASE_URL=... -t findmything-web:local frontend`: 0.
- Smoke: web container `GET /` 200 and `GET /some/spa/route` 200 (SPA fallback); api container `GET /api/health` 200 `{"status":"ok"}`, Docker health `healthy`, runs as `appuser`. Containers removed afterwards.

Not verified (by design): the Bicep templates were never deployed or `what-if`ed (needs an Azure subscription); the CI workflow was never run on GitHub; the API image was smoke-tested without a database (health only, `MATCHING_WORKER_ENABLED=false`).

Phase 4 is COMPLETE. Phase 5 (Power BI) not started.

---

### Phase 3 Frontend Completion Result (2026-11-25)
All figures below were produced by direct execution in this session:

- `npm run lint` (`eslint .`): **All checks passed (exit 0)**.
- `npx tsc -b` (Typecheck): **Success: 0 errors (exit 0)**.
- `npm test -- --run` (`vitest run`): **3 test files, 40 tests passed, 0 failed (exit 0)**.
- `npm run build` (`vite build`): **Production build succeeded in 869ms (exit 0)**.
  - Chunk: `dist/assets/index-B1Mb7JVW.js` (376.45 kB │ gzip: 113.51 kB).
  - Styles: `dist/assets/index-DWJuHcP5.css` (7.27 kB │ gzip: 1.88 kB).

---

## 1E. Session 2026-11-25 — Phase 3 Frontend Implementation Complete

### Delivered Workflows & Pages:
1. **P0: Student Workflows:**
   - **Authentication:** `SignInPage.tsx`, `RegisterPage.tsx`, `AuthProvider.tsx`, `auth-context.ts`, `RequireRole.tsx`. Session restoration on mount, CSRF auto-refresh, credential handling.
   - **Reporting:** `ItemSearchPage.tsx` (live query filters, URL search params sync, pagination), `ReportFormPage.tsx` (two-step create report + photo upload), `ReportDetailPage.tsx` (view details, photo upload/deletion, edit report details via `PATCH /reports/{id}`, withdraw report, claim submission with optional link to own lost report, matches panel with recalculation trigger).
   - **Student Dashboard:** `MyReportsPage.tsx` (withdrawn/closed tabs), `MyClaimsPage.tsx` (student claim overview, status badge, moderation note badges), `ClaimDetailPage.tsx` (view statement, moderator info requests and decision records, evidence photo upload up to 3 images, photo deletion, cancel claim).
2. **P1: Moderator Workflows:**
   - **Review Queue:** `ModeratorClaimsPage.tsx` (`GET /moderation/claims` with status tabs, pagination, claimant & found item links, evidence counts).
   - **Claim Detail Review:** `ModeratorClaimDetailPage.tsx` (`GET /moderation/claims/:claimId`, full timeline history, claimant details, evidence review with removal capability, verify claim, request info, reject with mandatory reasons, in-person recovery handover completion, and recovery voiding).
   - **Report Moderation:** `ReportDetailPage.tsx` moderation section (close report with reasons, reopen report, correct report fields with decision note auditing).
   - **Analytics & Activity:** `ModeratorAnalyticsPage.tsx` (KPIs, recovery rate, category & location breakdowns, monthly trends, date range filters), `ModeratorActivityPage.tsx` (tamper-evident platform activity feed with metadata inspection, outcomes, actors, pagination).
3. **P2: Routing & Layout:**
   - `routes.tsx` wired with `RequireRole` (`STUDENT`, `MODERATOR`), public fallbacks, `NotFoundPage.tsx`.
   - `Layout.tsx` and `HomePage.tsx` updated with dynamic role navigation links, brand skip-links, and keyboard focus management.
   - `main.tsx` mounts `<AuthProvider>` at the root.

---

## 1D. Session 2026-11-15 - Task 2.2 Administrative CLI and Retention Executor (COMPLETE and VERIFIED)

### State found on entry (recovered, nothing restarted)
The previous agent (usage limit hit) had created `backend/app/services/cleanup.py`, `backend/app/services/operator.py`, `backend/app/cli.py` and `backend/tests/test_retention_cleanup.py` (41 tests). All four were reviewed and kept; no production code needed changing. Run as `python -m app.cli <command>` from `backend/` with the venv.

### The four commands (all verified by tests AND by the real `python -m app.cli` entry point: `--help` exit 0 for the root and every subcommand; bad usage exit 2)
Exit codes: 0 ok, 1 operational failure, 2 usage/validation. Logging is WARNING+ and never carries SQL, parameters, keys, filenames or secrets (errors print the exception class name only).
1. `create-moderator`: interactive (name, email, hidden `getpass` password, confirmation, 3 attempts). No `--password`/`--email` flags, no default credentials, no public path (register hard-codes the STUDENT role and its schema forbids extra fields; tested). Argon2id hash. Refuses any existing email (case/space-insensitive) with `EMAIL_EXISTS` and never changes that account's role, password, name or active flag. Audited as `AUTH_REGISTERED` (actor NULL, metadata `role=MODERATOR`, `operator=OPERATOR`); the password never appears in output or audit. Missing role rows give `REFERENCE_DATA_MISSING`.
2. `seed-reference-data [--config <path>]` (default: configured campus file): deterministic UUIDs via `seed_id`; running it twice creates 0 rows; existing rows are never renamed (a WARNING is printed instead); all-or-nothing (a failure such as a location name already used under another slug rolls back everything, including rows inserted earlier in the same run; tested); invalid config (bad JSON, unknown timezone, unknown zone, duplicates, zone/location slug collision) exits 2 before touching the DB. Seeding never creates accounts.
3. `cleanup-retention [--dry-run]`: PERFORMS the purge (a scheduler alone is not used). Phases: (a) report photos and (b) claim evidence whose owning report/claim reached a terminal state (RESOLVED/WITHDRAWN/CLOSED; RECOVERED/REJECTED/CANCELLED) and whose `purge_after_utc` is due: eligibility is re-checked under the row lock, the Blob is deleted FIRST, then the metadata row is marked `DELETED` (never hard-deleted); Blob 404 = success; a storage failure leaves the metadata untouched (retried next run) and counts as failed; 5 consecutive storage failures stop that phase early; (c) orphan Blobs under `attachments/` with no SQL row and older than 24 h; (d) `activity_logs` older than 365 days in batches of 5000 (the cutoff itself is kept); (e) one `RETENTION_CLEANUP` audit event with counts only. Boundary is inclusive to the millisecond: eligible exactly at terminal time + 90 days, not 1 ms earlier. Repeat runs find nothing. Exit 1 if any failure or phase error (for example `STORAGE_NOT_CONFIGURED`). `--dry-run` counts and changes nothing, writes no audit.
4. `matching-jobs run [--max-jobs N]` / `list [--status S] [--limit N]` / `retry <job_id>`: `run` drives the EXISTING outbox worker (`matching_worker`: lease, 8 attempts, exponential backoff with jitter, stale-lease reclaim, DEAD); no new matching code, no external queue. Active leases, future backoff and DEAD jobs are left alone; exit 1 if a job went DEAD in that run. `list` prints ids and error codes only, never report titles. `retry` only accepts a DEAD job (`JOB_NOT_DEAD` / `JOB_NOT_FOUND` otherwise), resets it to PENDING with 0 attempts, never touches the report, and audits `MATCH_JOB_RETRIED` (actor NULL, `operator=OPERATOR`).

### Files
Created (previous agent, reviewed and kept): `backend/app/services/cleanup.py`, `backend/app/services/operator.py`, `backend/app/cli.py`, `backend/tests/test_retention_cleanup.py`. Created (this session): `backend/tests/test_cli.py` (66 tests). Modified (this session): `backend/tests/test_retention_cleanup.py` (3 test fixes + 2 exact-boundary tests; now 43 tests), `backend/tests/conftest.py` (see defect 1 below). No other tracked file was changed by this session (git status is cumulative and uncommitted from earlier tasks).

### Defects found and fixed this session (tests/setup only)
1. `conftest.py` did `os.environ.pop("LOCAL_BLOB_DIR")`, which was a no-op because pydantic-settings re-reads `backend/.env` (it sets a real dev `LOCAL_BLOB_DIR`). A test that resolved the store from settings therefore ran the cleanup executor, including the orphan sweep, against `backend\.localblob`. The directory was verified empty with no `attachments/` folder, so nothing was lost. Now `conftest` sets `LOCAL_BLOB_DIR=""` and `AZURE_STORAGE_ACCOUNT_URL=""` (an empty env value overrides the file), so no test can resolve a real store. Tests that need storage inject a `tmp_path` store.
2. Two retention tests were wrong (SQL Server datetime2(3) keeps milliseconds only; ids read after rows were deleted).
3. T-SQL: `Column.is_(False)` emits `IS 0` and fails; use `== False` (already allowed by the `E712` ignore).

### Results (executed this session, completed output inspected; real SQL Server 2022 at localhost,14333; readiness by pyodbc)
`ruff check app tests`: All checks passed. `mypy app`: no issues in 41 source files. `pytest -v tests/test_cli.py tests/test_retention_cleanup.py`: 109 passed. Full `pytest -v`: **353 passed, 0 failed, 1 warning (StarletteDeprecation), 321 s** (244 baseline + 109 new).

### Environment incident (not a code problem)
Mid-session Docker Desktop restarted: `findmything-sql` exited (255), a first full run was killed and its 75 failures were all "connection refused". `docker start findmything-sql` fixed it, but SQL Server needed several minutes after the unclean exit before accepting logins; the `docker` CLI also hung repeatedly (use `Start-Job` with a timeout) and pyodbc remains the reliable readiness check. Container and data were never deleted.

### Remaining defects / notes (none blocking Phase 3)
- `cleanup-retention` and `matching-jobs run` are on-demand commands; nothing schedules them yet. Scheduling (for example an Azure Container Apps job) belongs to Phase 4. No Azure resources were provisioned.
- The CLI was verified against the test database and a `tmp_path` store only; no cleanup was run against the dev database `findmything` or real user data (deliberate).
- Pre-existing, not changed: `matching_worker` logs failures with `log.exception`; for database errors that traceback can include bound SQL parameters. Consider logging only the exception class there.
- `create-moderator` reuses the existing `AUTH_REGISTERED` audit event type (frozen taxonomy; role and operator are in the metadata).
- `backend/photo_run.log` and `backend/photo_err.log` (earlier sessions) and `handoff/_*_run.log` (this session) are throwaway logs and can be deleted.

---

## 1C. Session 2026-11-14 — Task 2.1 Moderator Analytics and Activity API (COMPLETE and VERIFIED)

Both endpoints are implemented, database-backed and tested against real SQL Server 2022. No migration was added; no view was changed. Photo/evidence code was not touched.

### Endpoints (moderator only; student 403, anonymous 401; auth is checked before query validation)
- `GET /api/moderation/analytics/summary?from=YYYY-MM-DD&to=YYYY-MM-DD` (routes: `app/api/routes_analytics.py`, logic: `app/services/analytics.py`). Dates inclusive, campus-timezone local dates converted to UTC instants (half-open `[from 00:00, to+1 00:00)`). Default: the last 90 days inclusive through campus-today (`from = to - 89`). `from > to` -> 422; more than 366 days inclusive -> 422; bad date or unknown query parameter -> 422. Response keys exactly as contract 4.5, plus two ADDITIVE keys (see "Additions to confirm").
- `GET /api/moderation/activity?page=&page_size=` (+ optional `event_type`, `outcome`, `target_type`). Order `created_at_utc DESC, activity_id ASC` (contract 19), `{items,page,page_size,total}`, empty -> 200 `items=[]`, page past the end -> 200 empty items with the real `total`. Actor display name comes from one LEFT JOIN (no N+1). One audit source: reads the existing `activity_logs` table written by `audit.log_event`; no second audit system.

### Exact calculation definitions (contract 22; implemented in `analytics.py`)
- Cohort = reports whose `created_at_utc` falls in the campus-local inclusive date range. `lost_reports` / `found_reports` / `active_reports` (ACTIVE now, both types) use that cohort.
- **Recovery rate** = (FOUND reports in the cohort with a COMPLETED, non-voided recovery whose `completed_at_utc <= as_of_utc`) / (ALL FOUND reports in the cohort). WITHDRAWN and CLOSED stay in the denominator. `recovery_rate_non_withdrawn_pct` = same numerator / (cohort FOUND reports whose status is not WITHDRAWN); CLOSED stays. Both are rounded half-up to 1 decimal and are `null` (not 0) when the denominator is 0. Denominator = `found_reports`; numerator and both denominators are exposed in `recovery_rate_basis`; `period` shows from/to/`as_of_utc`.
- **Time to recovery** = `DATEDIFF_BIG(millisecond, report.created_at_utc, recovery.completed_at_utc)` for recovered cohort FOUND reports (physical completed recovery, never claim verification). Average and median (`PERCENTILE_CONT(0.5)`) in days, rounded half-up to 1 decimal, `null` when there are no qualifying recoveries.
- `claims.submitted` = claims created in the period; `claims.verified/rejected/cancelled` = `claim_status_history` transition EVENTS into that state in the period (a re-verification counts again).
- `recoveries` = COMPLETED (not voided) recoveries with `completed_at_utc` in the period and `<= as_of_utc`. This is the recovery-EVENT view and intentionally differs from the cohort numerator.
- `by_category` / `by_location`: cohort LOST/FOUND counts plus cohort FOUND recoveries per value; only values with at least one cohort report appear; sorted by name (case-insensitive) then UUID.
- `monthly`: campus-local report-creation months, zero-filled for every month the period touches; `recoveries` = recoveries of FOUND reports created in that month (not the event month). Bucketing is done in SQL via an inner query (SQL Server cannot match repeated bind parameters in GROUP BY).

### Privacy
Analytics returns aggregates only (counts, rates, category/location names): no user ids, names, emails, titles, descriptions, claim statements, notes, evidence or Blob data (asserted by a test with seeded secrets). Activity metadata is passed through `audit.sanitize_metadata` again at READ time (allowlist), non-object JSON becomes `{}`, and `decision_note` is returned only for `REPORT_CLOSED`, `REPORT_REOPENED`, `REPORT_MODERATOR_CORRECTED` (contract: only moderator report-action notes). `MATCH_DISMISSED` notes are deliberately withheld (fail closed).

### Additions to confirm with the owner (additive and non-breaking; flagged, not silently decided)
1. Analytics response has two extra keys beyond contract 4.5: `report_status_counts` (`lost`/`found` x ACTIVE/RESOLVED/WITHDRAWN/CLOSED) and `recovery_rate_basis` (`recovered_found_reports`, `found_reports`, `found_reports_non_withdrawn`). Reason: Blueprint 10.1 requires displaying the denominator and keeping withdrawn/closed visible, which the frozen shape cannot express. Remove them if the contract must be byte-exact.
2. Activity accepts optional `event_type` / `outcome` / `target_type` filters (validated; unknown values 422). Contract 4.5 lists only `page`/`page_size`; the task brief asked for filtering. Unknown parameter names still return 422.
3. The existing `vw_recovery_analytics` was NOT reused for the API because it rounds `days_to_recovery` per row, which would distort the contract's "average then round" definition. The view is unchanged for Power BI.

### Files
Created: `backend/app/services/analytics.py`, `backend/app/api/routes_analytics.py`, `backend/tests/test_analytics_api.py` (24 tests), `backend/tests/test_activity_api.py` (13 tests). Modified: `backend/app/main.py` (router mount only).

### Results (all executed this session, completed output inspected; real SQL Server 2022 at localhost,14333; readiness by pyodbc 15 s connect, `docker ps` never used)
- Focused: `pytest -v tests/test_analytics_api.py tests/test_activity_api.py`: **37 passed**, 1 warning (httpx/starlette deprecation), exit 0, 51.7 s (re-run after the last edit: 37 passed, 40.9 s).
- `ruff check app tests`: All checks passed (exit 0).
- `mypy app`: Success, no issues in 38 source files (exit 0); no new `Any` or `type: ignore`.
- Full `pytest -v`: **244 passed**, 0 failed, 0 errors, 1 warning, 379.8 s (= 207 baseline + 37 new). Per file: activity 13, analytics 24, auth 25, claim evidence 37, claims 27, matching api 15, matching domain 13, report photo 53, reports 24, schema 13.

### Remaining defects / notes
- None known for Task 2.1. Not covered by tests: very large datasets (queries are aggregate-only; indexes `ix_reports_browse`, `ix_activity_time` exist), a DST campus timezone (tests use Asia/Kolkata, UTC+05:30; boundaries are built with `zoneinfo`, so DST zones are handled by construction but unverified).
- Stray untracked logs `backend/photo_err.log`, `backend/photo_run.log`, `handoff/_claim_evidence_run.log` still present (safe to delete). Nothing committed or pushed.

---

## 1B. Session 2026-11-13/14 — Claim Evidence Recovery, Verification and Completion (supersedes 1A where they differ)

**Claim evidence is COMPLETE and VERIFIED.** Phase 2 Task 2.0 (report photo + claim evidence) is done.

### State found on entry (recovered, nothing restarted)
The earlier agent's claim-evidence work was already complete in the tree, contrary to the 1A note that it was unrouted and untested:
- `backend/app/api/routes_claims.py`: `POST /api/claims/{id}/evidence` (multipart `files[]`, 201 `{evidence:[...]}`), `GET /api/claims/{id}/evidence/{evidence_id}` (authorized stream via shared `file_response`), claimant `DELETE` (204), moderator `DELETE /api/moderation/claims/{id}/evidence/{evidence_id}` (body `{reason_code,decision_note?}`, 204).
- `backend/app/services/attachments.py`: `upload_claim_evidence`, `get_claim_evidence`, `delete_own_evidence`, `moderator_delete_evidence`; reuses `process_image`, `get_blob_store`, `audit.log_event`, `lock_claims`; no duplicated image/storage logic.
- `backend/tests/test_claim_evidence_api.py`: 37 test cases (real SQL Server, real generated images from `tests/image_fixtures.py`, `LocalBlobStore`, failing-store subclass).
- No application or test code was changed this session; the work was verification.

### Behavior verified by the tests
Upload (JPEG/PNG/WebP re-encoded, metadata stripped, random `attachments/<uuid>.<ext>` key, claim version bumped once per request, status and `status_changed_at_utc` untouched); 3-image total limit (409 `EVIDENCE_LIMIT_EXCEEDED`, atomic for 2+2 and 4-in-one); invalid/corrupt/empty (422), GIF/BMP (415), oversized (413), one bad file rejects the batch; terminal claims reject upload (409 `CLAIM_NOT_ACTIVE`); upload denied for moderator (403), report owner / unrelated student (404 concealment), anonymous (401); retrieval for claimant and moderator only with `private, no-store`, `nosniff`, fixed inline filename; moderator access audited (`MODERATOR_EVIDENCE_ACCESSED`) on every access and not audited when storage fails; report owner and unrelated students never receive evidence; evidence id of another claim, unknown/deleted id, missing Blob -> 404; storage outage on get/put/delete -> 503 with metadata and Blob state consistent; partial multi-file put failure removes already-written Blobs; SQL/audit failure after Blob write removes Blobs and rolls back; DB rows match Blob store exactly; delete flow and moderator-delete reason validation.

### Test results (executed this session, output inspected; real SQL Server 2022 at localhost,14333)
- `pytest -v tests/test_claim_evidence_api.py`: **37 passed**, 1 warning (httpx/starlette deprecation), exit 0, 179.5 s.
- `ruff check app tests`: All checks passed (exit 0).
- `mypy app`: Success, no issues in 36 source files (exit 0).
- `pytest -v tests/test_report_photo_api.py`: **53 passed**, exit 0, 95.8 s (first time these ever ran against SQL Server).
- Full suite `pytest -q`: **207 passed**, 1 warning, 0 failed, 0 errors, 438 s (= 117 baseline + 37 evidence + 53 photo).

### Environment notes
- `docker ps` hung (20 s timeout) even though SQL Server was healthy; do not use it as the readiness check. Use a pyodbc connect with a 15 s timeout. The container was not touched.
- Use `backend\.venv\Scripts\python.exe` / `pytest.exe`; system Python lacks project dependencies.
- Never run overlapping pytest processes against the shared test DB. A long pytest started from a tool call can outlive the call; check `Get-CimInstance Win32_Process` for `pytest` first and write output to a log file.

### Files changed (all uncommitted)
`app/api/routes_claims.py`, `app/api/routes_reports.py`, `app/services/attachments.py` (new), `app/services/images.py`, `tests/image_fixtures.py` (new), `tests/test_report_photo_api.py` (new), `tests/test_claim_evidence_api.py` (new), plus the Phase 1 files listed above. Stray untracked logs `backend/photo_err.log`, `backend/photo_run.log`, `handoff/_claim_evidence_run.log` are leftovers; safe to delete, left in place.

### Remaining gaps (non-blocking)
- Azure Blob adapter is exercised only through the `BlobStore` interface (no live Azure test; no provisioning in scope).
- Task 2.0B hardening items (non-owner student GET of photo on WITHDRAWN/CLOSED report, `has_photo` in report DTOs per contract line 249) were not re-audited this session; the 53 photo tests pass, but check these against the contract when next touching reports.
- Still missing from the contract: analytics/activity routes (Task 2.1), CLI + retention executor (Task 2.2).

---

## 1A. Session 2026-11-12 — Report Photo Upload (supersedes the Photo row and gap #1/#6 below where they differ)

### What the previous agent (usage limit hit) had already implemented — all valid, preserved
- `backend/app/services/attachments.py` (NEW): report-photo `upload_report_photo` / `get_report_photo` / `delete_report_photo`, plus claim-evidence service functions (`upload_claim_evidence`, `get_claim_evidence`, `delete_own_evidence`, `moderator_delete_evidence`). Flow: validate+re-encode -> lock -> re-check -> Blob put -> metadata insert; compensating Blob delete on any failure; Blob delete before soft-delete (503, metadata retained, on Blob failure).
- `backend/app/api/routes_reports.py`: `POST/GET/DELETE /api/reports/{id}/photo` wired (multipart field `file`, 201 / authorized stream with `private, no-store` + `nosniff` + fixed inline filename / 204). Reads at most MAX_BYTES+1 from the upload.
- `backend/app/services/images.py`: 415 `UNSUPPORTED_MEDIA_TYPE` for non-JPEG/PNG/WebP and animated; metadata (`img.info`, ICC, comments) dropped before re-encode except PNG/palette transparency.
- `backend/tests/image_fixtures.py` (NEW, generated real images carrying a marker in EXIF/GPS/comment/PNG text) and `backend/tests/test_report_photo_api.py` (NEW, 28 test cases; real SQL Server fixtures, `LocalBlobStore`, failing-store subclass for 503/compensation paths, real Pillow decode of stored bytes).

### What this session did
- Inspected `git status/diff` and untracked files; located all files above; confirmed upload endpoint is IMPLEMENTED (not tests-only) and matches contract lines 40, 72, 157, 307, 369-370, 443.
- Read all of `attachments.py`, the route diff, and both test files; tests assert real behavior (decoded stored bytes, DB rows, blob store contents, audit rows), not mocked responses.
- Fixed Ruff B007 in `attachments.py` (`for row in rows` -> `for _ in rows` in `upload_claim_evidence`). Only code change this session.
- Verified without SQL: all fixtures through `process_image` directly: JPEG/PNG/WebP re-encode with marker removed and EXIF empty; EXIF orientation 6 baked into pixels (40x20 -> 20x40); PNG alpha kept; corrupt/truncated/empty -> 422 `INVALID_IMAGE`; GIF/BMP -> 415; 5,000,000+ byte PNG -> 413 `PAYLOAD_TOO_LARGE`.

### Files changed (all uncommitted)
Previous agent + this session, photo-related: `app/api/routes_reports.py`, `app/services/attachments.py` (new), `app/services/images.py`, `tests/image_fixtures.py` (new), `tests/test_report_photo_api.py` (new). Earlier-session changes still present (see Phase 1 list above).

### Test results (2026-11-12, executed this session)
- `ruff check app tests`: All checks passed (exit 0) — after the B007 fix.
- `mypy app`: Success, no issues in 36 source files (exit 0).
- `pytest -q tests/test_matching_domain.py`: 13 passed.
- `pytest -v tests/test_report_photo_api.py`: **NOT VERIFIED — 28 errors at fixture setup, 0 tests executed.** Cause: SQL Server unreachable (`pyodbc 08001, prelogin timeout 258`). TCP port 14333 accepts connections but SQL Server does not answer prelogin; `docker ps` / `docker info` hang (Docker Desktop processes present, engine not responding). Four 10 s retries over ~40 s also failed. Container was NOT touched (no rm/restart/reset); SQLite NOT substituted.
- Full regression suite: NOT RUN (same blocker). Last known baseline: 117 passed (2026-11-11).

### Remaining defects / risks
1. The 28 photo tests have never been run against SQL Server by anyone. Failures are possible in: `FailingStore`/`store.list()` use (confirm `LocalBlobStore.list` and `set_blob_store` exist and behave), the CSRF test (`owner.http.post`), `test_sql_failure_after_blob_write_removes_the_blob` (monkeypatches `audit.log_event`, rebuilds TestClient), and the filtered unique index race path (`IntegrityError` branch).
2. Scope note: the previous agent also wrote claim-evidence SERVICE functions in `attachments.py`. They are NOT routed (`routes_claims.py` is unmodified) and have no tests. Left in place unchanged (other than the lint fix); do not extend without the claim-evidence task.
3. `GET`/`DELETE` report-photo routes are also already implemented and covered by the same test file; Task 2.0B is therefore verification/hardening rather than greenfield.
4. `retention.py` purge executor, analytics/activity routes, CLI: unchanged, still missing (Phase 2.1/2.2).

---

## 2. Repository Structure

```text
C:\Users\ASUS\Desktop\FindMyThing\
├── .gitignore
├── AGENTS.md                  # Development guidelines, invariants, precedence rules
├── README.md                  # Project overview and run instructions
├── backend\
│   ├── .env                   # Local dev/test database connection strings
│   ├── .env.example           # Reference environment configuration
│   ├── alembic.ini            # Alembic configuration
│   ├── pyproject.toml         # Python packaging, Ruff, Pytest, Mypy configs
│   ├── app\
│   │   ├── main.py            # FastAPI factory, CORS, exception handlers, router mounts
│   │   ├── api\               # deps.py, routes_auth, routes_reports, routes_matches, routes_claims
│   │   ├── core\              # config, errors, ratelimit, security (Argon2id/tokens), text
│   │   ├── domain\            # matching.py (match-v1 pure scoring engine)
│   │   ├── persistence\       # database.py, models.py (SQLAlchemy 2 entities), results.py (typed `affected_rows()`)
│   │   ├── schemas\           # base.py (Pydantic request/response models)
│   │   └── services\          # audit, auth, blobstore, claims, images, locking, matches, matching_worker, reports, retention, seed
│   ├── migrations\
│   │   ├── env.py
│   │   └── versions\
│   │       └── 0001_initial.py # Schema DDL, triggers, analytics views, indexes
│   └── tests\                 # 117 test cases (domain unit tests + SQL Server integration tests)
├── config\
│   └── campus.example.json    # Reference taxonomy (categories, zones, locations)
├── docs\                      # Authoritative specifications (F1-F6 scope, contracts, architecture)
├── research\                  # Technical research whitepaper (PDF)
├── scripts\
│   └── dev_db.py              # Local Docker SQL Server helper script
└── handoff\                   # Authoritative handoff documentation
    ├── STATUS.md
    ├── IMPLEMENTATION_PLAN.md
    └── NEXT_AGENT.md
```

---

## 3. Subsystem Implementation & Audit Matrix

| Subsystem | Status | Relevant Files | Verified? | Notes |
| :--- | :--- | :--- | :--- | :--- |
| **Domain: Matching Engine** | `VERIFIED` | [matching.py](file:///C:/Users/ASUS/Desktop/FindMyThing/backend/app/domain/matching.py) | **Yes** (13/13 unit tests incl. frozen-weight and formula tests) | Pure `score_pair()`, 40/25/25/10 weights (Blueprint s6 / D-012), threshold 50 inclusive, 30-day window, deterministic ranking. |
| **Persistence: Schema & Models** | `IMPLEMENTED_TESTED` | [models.py](file:///C:/Users/ASUS/Desktop/FindMyThing/backend/app/persistence/models.py), [0001_initial.py](file:///C:/Users/ASUS/Desktop/FindMyThing/backend/migrations/versions/0001_initial.py) | **Yes** (13 tests, `test_schema_sql.py`, real SQL Server) | Tables, FKs, status-history trigger, analytics views, filtered unique indexes. |
| **Auth & Security** | `IMPLEMENTED_TESTED` | [routes_auth.py](file:///C:/Users/ASUS/Desktop/FindMyThing/backend/app/api/routes_auth.py), [security.py](file:///C:/Users/ASUS/Desktop/FindMyThing/backend/app/core/security.py), [ratelimit.py](file:///C:/Users/ASUS/Desktop/FindMyThing/backend/app/core/ratelimit.py) | **Yes** (25 tests, `test_auth_api.py`) | Argon2id, opaque 12h sessions, Origin check, CSRF, SQL-backed rate limits. |
| **Reports (F1/F2) core lifecycle** | `IMPLEMENTED_TESTED` | [routes_reports.py](file:///C:/Users/ASUS/Desktop/FindMyThing/backend/app/api/routes_reports.py), [reports.py](file:///C:/Users/ASUS/Desktop/FindMyThing/backend/app/services/reports.py) | **Yes** (24 tests) | Create/list/detail/edit/withdraw/close/reopen/correct, `GET /reference-data`. Photo routes are NOT implemented (see Photo row). |
| **Matches & Matching Worker** | `IMPLEMENTED_TESTED` | [routes_matches.py](file:///C:/Users/ASUS/Desktop/FindMyThing/backend/app/api/routes_matches.py), [matches.py](file:///C:/Users/ASUS/Desktop/FindMyThing/backend/app/services/matches.py), [matching_worker.py](file:///C:/Users/ASUS/Desktop/FindMyThing/backend/app/services/matching_worker.py) | **Yes** (15 tests) | List, dismiss, recalculate, SQL outbox with leases. |
| **Claims & Recovery (F3/F4) core** | `IMPLEMENTED_TESTED` | [routes_claims.py](file:///C:/Users/ASUS/Desktop/FindMyThing/backend/app/api/routes_claims.py), [claims.py](file:///C:/Users/ASUS/Desktop/FindMyThing/backend/app/services/claims.py), [locking.py](file:///C:/Users/ASUS/Desktop/FindMyThing/backend/app/services/locking.py) | **Yes** (27 tests) | Submit/cancel, moderator verify/reject/revoke/request-information, recover, void recovery. Evidence upload/get/delete routes are NOT implemented (see Photo row). |
| **Photo / Evidence Upload & Storage** | `REPORT_PHOTO_IMPLEMENTED_UNVERIFIED_ON_SQL` (see section 1A; row text below is the 2026-11-11 baseline and is superseded) | [images.py](file:///C:/Users/ASUS/Desktop/FindMyThing/backend/app/services/images.py), [blobstore.py](file:///C:/Users/ASUS/Desktop/FindMyThing/backend/app/services/blobstore.py), [retention.py](file:///C:/Users/ASUS/Desktop/FindMyThing/backend/app/services/retention.py) | **No** (zero tests reference them) | `process_image()` and `LocalBlobStore`/`AzureBlobStore` exist but have NO callers anywhere in `app/`. No upload/download/delete routes. `retention.py` only schedules/cancels `purge_after_utc`; nothing executes a purge. |
| **Analytics & Moderation Feed** | `IMPLEMENTED_TESTED` (2026-11-14, Task 2.1; see section 1C) | [analytics.py](file:///C:/Users/ASUS/Desktop/FindMyThing/backend/app/services/analytics.py), [routes_analytics.py](file:///C:/Users/ASUS/Desktop/FindMyThing/backend/app/api/routes_analytics.py), views `vw_recovery_analytics`, `vw_claim_transition_analytics` (unchanged) | **Yes** (24 analytics + 13 activity tests, real SQL Server) | `GET /api/moderation/analytics/summary` and `GET /api/moderation/activity` implemented per contract 4.5/19/22. The row text in older sections that calls these missing is obsolete. |
| **CLI Management Tools** | `NOT_STARTED` | `scripts/dev_db.py` only | No | `backend/app/cli.py` does not exist. Contract requires `create-moderator`, `seed-reference-data`, `cleanup-retention`, `matching-jobs list/retry`. |
| **Frontend SPA (F5)** | `NOT_STARTED` | `frontend/` (directory does not exist) | No | React + TypeScript + Vite + Tailwind/CSS, client router, session/CSRF state, all views (search, report form, claim form, moderator dashboard) missing. |
| **Azure Deployment Scaffolding (F6)** | `NOT_STARTED` | `infra/`, `.github/workflows/` | No | Bicep templates (App Service, Azure SQL, Blob Storage), Dockerfiles, and CI/CD pipelines missing. |
| **Power BI Integration** | `NOT_STARTED` | N/A | No | Power BI direct query/PBIX or semantic model configuration not yet created. |

---

## 4. Resolved Defects & Remaining Backend Gaps

### Resolved (Phase 1)
1. Ruff: 4 `E501` violations fixed by wrapping lines in `blobstore.py` and `claims.py`.
2. MyPy: 37 errors fixed properly. `require()` narrows Optional ORM lookups whose absence would mean a broken FK invariant (raises `DataIntegrityError`, surfaced as the generic 500 envelope, never a client 4xx). `affected_rows()` narrows `Result` to `CursorResult` for DML rowcounts. PIL variable annotated `Image.Image`. Alembic head `None` guarded.
3. SQL Server container `findmything-sql`: running, port 14333, recovery of DB `findmything` completed per container log, integration suite executes fully. `docker inspect` shows `Mounts: []` (no volumes), so data lives only in the container layer: **never `docker rm` / recreate it**. The cause of the earlier hang is not confirmed.

### Remaining backend gaps vs `docs/IMPLEMENTATION_CONTRACTS.md` (found by route and CLI inventory this session)
Route inventory of `backend/app/api/` shows 31 routes (health, auth, reports, matches, claims, reference-data) and none of the following required ones:
1. **Report photo** (contract line 72): `POST /api/reports/{id}/photo` (multipart `file`, owner, ACTIVE/RESOLVED, one photo, 409 if present), `GET` (authorized stream, `Cache-Control: private, no-store`, `nosniff`), `DELETE` (owner or moderator, 204).
2. **Claim evidence** (lines 95, 311): `POST /api/claims/{id}/evidence` (multipart `files[]`, claimant, PENDING/VERIFIED, max 3 total, 409 on overflow), `GET /api/claims/{id}/evidence/{evidence_id}` (claimant or moderator, audited), `DELETE` by claimant, and moderator `DELETE /api/moderation/claims/{id}/evidence/{evidence_id}` (reason `OTHER` or `INSUFFICIENT_EVIDENCE`; `OTHER` needs a note). Blob delete failure returns 503 and keeps metadata.
3. ~~**Analytics** (lines 99-100): `GET /api/moderation/analytics/summary` and `GET /api/moderation/activity`.~~ DONE 2026-11-14 (Task 2.1, section 1C).
4. **CLI** (lines 222-225): `python -m app.cli` with `create-moderator`, `seed-reference-data`, `cleanup-retention`, `matching-jobs list --status DEAD` / `matching-jobs retry <job_id>`.
5. **Retention executor** (lines 162-167): nothing performs the 90-day attachment/evidence purge (Blob first, then mark metadata deleted; Blob 404 = success; orphan Blobs older than 24 h) or the 365-day `activity_logs` purge. Only scheduling exists.
6. **Test gaps:** no test references `process_image`, the blob stores, or retention.

Note: the earlier `IMPLEMENTATION_PLAN.md` Task 2.2 text (`matching-jobs run-once`, `purge_expired_data()`, `--email/--name/--password` flags) diverged from the contract; the plan has been corrected. The contract governs.

### Not yet audited in depth
This session verified matching against the frozen spec and inventoried routes/CLI. It did not re-audit the RBAC matrix, report/claim state machines, or audit-log allowlists line by line beyond what the 117 passing tests cover.

---

## 5. Specification Deviations & Resolved Inconsistencies

All deviations are documented in [docs/IMPLEMENTATION_NOTES.md](file:///C:/Users/ASUS/Desktop/FindMyThing/docs/IMPLEMENTATION_NOTES.md):
- **N-001 (SQL Server Error 10609 on Computed Columns):** Spec §6/§26 required computed guard columns with filtered unique indexes. SQL Server disallows filtered unique indexes on computed columns. Resolved by applying filtered unique indexes directly to base columns with `WHERE status IN (...)`. Invariants are identically preserved.
- **N-002 (Moderator Correction of Terminal Reports):** Contract §2 specified ACTIVE only; §4.2 allowed terminal reports. Resolved in favor of §4.2 (corrections permitted on terminal reports, which invalidate matches but do not re-enqueue matching).
- **N-003 (Image Output Format):** Contract §9 specified JPEG normalization; §21 specified re-encoding to the same allowed format (JPEG/PNG/WebP). Resolved by preserving original container format while re-encoding to strip EXIF metadata.
- **A-005 (Reference Data Route):** Added `GET /api/reference-data` to expose campus taxonomy to frontend clients.
- **A-010 (Search Implementation):** Used parameterized `LIKE` query instead of full-text catalog for portable campus-scale matching.

---

## 6. Test Execution Results (2026-11-11, executed this session)

- `ruff check app tests`: **All checks passed** (exit 0).
- `mypy app`: **Success: no issues found in 35 source files** (exit 0).
- `pytest -v tests/test_matching_domain.py`: **13 passed** in 0.17 s.
- Full `pytest -v` (real SQL Server 2022, port 14333): **117 passed, 0 skipped, 0 failed, 1 warning in 143 s** (exit 0).
  - test_auth_api 25, test_claims_api 27, test_matching_api 15, test_matching_domain 13, test_reports_api 24, test_schema_sql 13.
  - Warning: `StarletteDeprecationWarning` (httpx with `starlette.testclient`), third-party, not actionable here.
- Integration coverage is real SQL Server 2022 only; SQLite was never substituted.
