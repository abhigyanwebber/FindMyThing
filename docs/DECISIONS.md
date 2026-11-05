# Decision Register — FindMyThing

This register is authoritative for frozen project-level decisions. Detailed implementation rules are in `BLUEPRINT.md` and `IMPLEMENTATION_CONTRACTS.md`; architecture structure is in `ARCHITECTURE.md`.

| ID | Decision | Status | Notes |
|---|---|---|---|
| D-001 | Product is a secure campus lost-and-found and recovery platform | Frozen | F1–F6 complete agreed scope |
| D-002 | Scope is F1–F6 in `MVP_SCOPE.md` (historical filename, not reduced MVP) | Frozen | No scope expansion without explicit change approval |
| D-003 | Use a small modular monolith | Frozen | FastAPI single deployment; no microservices |
| D-004 | React + TypeScript + Vite frontend | Frozen | Azure Static Web Apps |
| D-005 | FastAPI + Python backend | Frozen | Azure App Service |
| D-006 | Azure SQL Database | Frozen | Verify actual subscription quota/cost before provisioning |
| D-007 | Private Azure Blob Storage for photos/evidence | Frozen | Backend authorization; random object keys |
| D-008 | Azure Static Web Apps frontend | Frozen | Azure-native hosting |
| D-009 | Azure App Service backend | Frozen | Verify available plan/quota/cost |
| D-010 | SQL analytics view/read model + Power BI Desktop | Frozen | Power BI Service not assumed |
| D-011 | Server-side sessions + Argon2id | Frozen | Same-site custom domains, Secure/HttpOnly/SameSite=Lax cookie, CSRF token, explicit CORS |
| D-012 | Deterministic persisted matching after report creation/material changes | Frozen | `match-v1`, score weights 40/25/25/10, threshold 50, SQL outbox/retry |
| D-013 | Azure for Students intended subscription | Frozen direction | Actual service availability/cost is portal verification, not guaranteed free |
| D-014 | Architecture/Blueprint are course-informed and frozen before implementation | Frozen | Implementation requires separate explicit owner instruction |
| D-015 | AZ-900/AI-900 are learning context, not runtime products | Frozen | No AI feature implied |
| D-016 | Tech Stack = what; Architecture = structure/interactions; Blueprint = exact implementation | Frozen | Trio must remain coherent |
| D-017 | Report states ACTIVE, RESOLVED, WITHDRAWN, CLOSED | Frozen | See Blueprint |
| D-018 | Claim states PENDING, VERIFIED, RECOVERED, REJECTED, CANCELLED | Frozen | Verification separate from recovery |
| D-019 | Multiple pending claims allowed; one verified winner per FOUND and linked LOST | Frozen | SQL constraints + transactions |
| D-020 | Recovery resolves FOUND and optional linked LOST report atomically | Frozen | Competing pending claims rejected; voided recovery attempts remain in history; later re-recovery creates a new recovery row |
| D-021 | Report status history uses narrow SQL Server trigger | Frozen | Claim history/application audit in transaction |
| D-022 | Photos optional; one report photo (5MB), up to three claim evidence photos (5MB each) | Frozen | JPEG/PNG/WebP; private Blob |
| D-023 | Moderator provisioning via interactive operator CLI | Frozen | No public role self-elevation/default credentials |
| D-024 | Audit retention 365 days; photos/evidence purge 90 days after terminal state | Frozen | SQL workflow records retained |
| D-025 | Matching work queue is SQL-backed durable outbox | Frozen | No Kafka/Redis/external broker; retry max 8 attempts |
| D-026 | Same-site custom frontend/API domains are required for production session topology | Frozen | If unavailable, pause deployment and request owner decision |
| D-027 | Detailed implementation behavior is governed by `IMPLEMENTATION_CONTRACTS.md` | Frozen | API, validation, privacy, schema types, session/CSRF, rate limiting, seed data, retention, operations, and tests are fixed there |
| D-028 | Authenticated users only may browse reports; no public anonymous report browsing | Frozen | Visibility rules in Implementation Contracts |
| D-029 | Report photo is a separate post-create upload; moderators cannot submit claims | Frozen | No multipart create-report/photo combined request or moderator exception |
| D-030 | SQL Server + pyodbc/ODBC Driver 18, managed identity Blob access, SQL migrations as one-off deployment step | Frozen | See Implementation Contracts; no Redis/Kafka |

## Change control

Any change to product scope, report/claim state semantics, matching algorithm/threshold, security topology, or transaction invariants must be explicitly approved by the project owner and recorded here before implementation. Exact package versions, Azure region/tiers, quota, domain purchase, and costs are verified at deployment.
