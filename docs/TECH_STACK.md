# Technology Stack — Selected Direction

## Status

**Frozen v1.0 — selected stack.** This document defines **what technologies are used**. Architecture defines component structure and interactions; Blueprint defines implementation contracts and detailed configuration. These three documents are intended to be read together and must not override one another.

The technology stack is frozen at the project level. Exact library/package versions and Azure resource tiers/region are verified during implementation/deployment; they do not authorize replacing this stack. Do not independently substitute technologies.

## Application stack

| Layer | Selected technology | Purpose |
|---|---|---|
| Frontend | React + TypeScript + Vite | Campus web UI |
| Frontend hosting | Azure Static Web Apps | Host static frontend |
| Backend | FastAPI + Python | REST API and application logic |
| Backend hosting | Azure App Service | Host the API |
| Relational database | Azure SQL Database | Users, reports, claims, workflow, audit records |
| Object storage | Azure Blob Storage | Item photographs; private storage |
| Analytics | SQL analytics view + Power BI Desktop | University analytics/reporting deliverable |
| Authentication | Server-side sessions + Argon2id password hashing | Session-based authentication |
| API style | REST/JSON | Frontend-to-backend integration |
| Database access/migrations | SQLAlchemy (Core/ORM) and Alembic | Persistence and schema evolution |
| Testing | pytest and API/integration tests | Verify behavior and security |

## Deployment direction

Azure-native hosting has been selected:

- Azure Static Web Apps — frontend
- Azure App Service — FastAPI backend
- Azure SQL Database — relational data
- Azure Blob Storage — photos
- Power BI Desktop — analytics/reporting

The project uses an **Azure for Students** subscription as the intended subscription basis. Actual quota, service availability, and cost must be verified in the user's Azure portal before provisioning. Do not assume every service or tier is free merely because the subscription is Azure for Students.

## Important deployment caveat

Frontend and API may be on separate origins. The exact origin/cookie/CSRF/CORS configuration is frozen in `ARCHITECTURE.md`, `BLUEPRINT.md`, and `IMPLEMENTATION_CONTRACTS.md`. Do not improvise security settings during implementation.

## Stack selection constraints

- No Vercel as the planned hosting provider; Azure-native deployment was chosen for Azure/cloud learning and project alignment.
- Do not add Redis, Kafka, Cosmos DB, Kubernetes, microservices, or other infrastructure without explicit owner approval.
- Azure SQL is the selected database direction; do not switch to PostgreSQL without owner approval.
- Power BI Desktop is the baseline. Power BI Service publishing/licensing is not assumed.
