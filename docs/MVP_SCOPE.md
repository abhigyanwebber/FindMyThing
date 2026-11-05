# Project Scope and Requirements Boundary

## Status

This file retains its historical filename for repository compatibility. It defines the **complete agreed core project scope**, not a reduced MVP. The six capabilities were defined in research and confirmed by the owner. Detailed acceptance criteria and workflows belong in the Blueprint.

## In-scope capabilities

### F1 — Authentication and role-based access control

- Student and moderator roles.
- Registration, login, logout, and authenticated identity.
- Backend-enforced authorization.
- Users must not be able to elevate their role or impersonate another user through client-supplied fields.

### F2 — Lost and found reporting

- Students create lost-item and found-item reports.
- Reports contain descriptive and campus-context information.
- Reports can be browsed and filtered.
- Item photographs may be attached under approved upload constraints.

### F3 — Deterministic potential matching

- Compare eligible lost reports against eligible found reports.
- Use transparent, explainable criteria rather than AI/ML.
- Display results as possible matches, never as confirmed ownership.
- Research-defined matching weights are retained in Architecture and Blueprint; detailed scoring normalization, thresholds, and lifecycle mechanics are specified in Blueprint.

### F4 — Claim, moderator verification, and recovery

- Students submit claims against eligible found reports.
- Moderators review claims and verify recovery.
- Claim approval and report recovery must be handled consistently and atomically at the database level.
- Sensitive claimant information must be restricted to authorized users.

### F5 — Activity/audit logging

- Record important security and business workflow actions.
- Do not log passwords, session secrets, SAS tokens, or sensitive claim text.
- Exact event taxonomy and retention are Blueprint decisions.

### F6 — Analytics dashboard

- Provide analytics relevant to lost/found reports and recovery.
- SQL analytics/read-model output feeds Power BI Desktop.
- Operational data changes remain within the application/API, not the analytics tool.

## Explicitly out of scope for the agreed project

Do not implement or propose these as project requirements unless the owner explicitly reopens scope:

- AI/LLM matching or assistants
- Computer vision or image recognition
- Vector databases or semantic search
- Chat or messaging
- Notifications
- Native mobile application
- Microservices
- Kubernetes
- Kafka
- Redis
- Payments
- Other unnecessary distributed infrastructure

## Scope-control rule

Any proposed feature must identify:

1. Which frozen project feature or rubric requirement it serves.
2. The implementation and testing cost.
3. What existing work it displaces or complicates.

If it does not materially support the project or rubric, defer it.
