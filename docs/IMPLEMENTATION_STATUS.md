# Implementation Status

**Current phase:** Local implementation in progress (owner authorized implementation; Azure provisioning not authorized yet).

## Frozen documentation

- [x] Complete F1–F6 scope boundary
- [x] Technology stack and Azure direction
- [x] Architecture and component boundaries
- [x] Report lifecycle and transitions
- [x] Claim lifecycle, competing claims, verification, recovery, and recovery void
- [x] Matching algorithm, persistence, invalidation, SQL outbox, and retry
- [x] Database entities, constraints, and transaction invariants
- [x] Authentication/session/CORS/CSRF topology
- [x] Moderator provisioning
- [x] Photo/evidence handling and retention
- [x] Analytics definitions and access
- [x] Audit/history strategy and retention
- [x] Cross-document consistency review
- [x] API/validation/visibility implementation contracts
- [x] SQL Server schema implementation decisions
- [x] Session/CSRF/rate-limit contracts
- [x] Seed data, reason/event enums, retention, deployment and maintenance contracts
- [x] Final whole-repository contradiction/readiness validation

## Implementation progress (local; verified against a real SQL Server 2022 container)

Done and tested:
- [x] Backend scaffold (FastAPI, SQLAlchemy 2, pyodbc/ODBC Driver 18, Alembic) in `backend/`
- [x] Alembic migration `0001_initial`: all tables, constraints, filtered unique indexes, report status-history trigger, analytics views
- [x] Idempotent reference-data seed (deterministic UUIDv5)
- [x] Auth: register/login/logout/me/csrf, Argon2id, hashed opaque sessions, 12h absolute expiry, CSRF + exact Origin, SQL-backed rate limits
- [x] Error envelope, request IDs, CORS, security headers, audit logging with metadata allowlist
- [x] Reports: create/list/search/detail/edit/withdraw, moderator close/reopen/correct, visibility rules, version conflicts, matching outbox enqueue + invalidation
- [x] Pure `match-v1` scoring domain
- [x] Tests: 72 passing (domain, SQL schema/trigger/invariants, auth API, reports API)

Not done yet:
- [ ] Matching worker + matches API (list/recalculate/dismiss)
- [ ] Claims, verification, recovery, recovery void, claim evidence
- [ ] Photo upload/retrieval, image re-encoding, Blob adapter, retention cleanup
- [ ] Moderator analytics summary + activity feed
- [ ] CLI (`create-moderator`, `seed-reference-data`, `cleanup-retention`, `matching-jobs`)
- [ ] React + TypeScript + Vite frontend, Vitest and Playwright tests
- [ ] Azure deployment scaffolding (Bicep, App Service / Static Web Apps config, CI workflows)
- [ ] Operational documentation, local-setup guide, Azure provisioning handoff
- [ ] Azure resource provisioning and integration (separate phase, not authorized)
- [ ] Power BI report

See `IMPLEMENTATION_NOTES.md` for spec discrepancies and assumptions found so far.

## Rule

Implementation is authorized. Do not commit, push, provision Azure resources, or deploy without a separate explicit owner instruction. Azure service quotas, region, plans, costs, and domain availability must be checked before deployment; this is a deployment verification task, not permission to redesign the project.