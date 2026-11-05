# Course and Rubric Alignment

## Purpose

The Architecture and Blueprint must be designed to demonstrate course learning, not merely produce a functioning website. Course alignment should influence design decisions and evidence, but it must not create unnecessary features.

The owner specifically mentioned **System Design, DBMS/RDBMS, Azure/cloud courses, Design Thinking, AZ-900, and AI-900** as relevant learning context. The earlier research report also mapped the project to web development, programming, networks, software engineering, and data/cloud fundamentals. Do not claim the owner completed a course unless they confirm it.

## Course-informed design targets

| Course / learning area | What FindMyThing should demonstrate | Guardrail |
|---|---|---|
| System Design | Requirements, component responsibilities, modular boundaries, interactions, tradeoffs, failure handling, deployment design | Use a small modular monolith; don't add microservices for appearance |
| DBMS / RDBMS | ER modelling, normalization, PK/FK, constraints, joins, indexes, views, triggers, transactions, integrity | Model genuine entities; don't create artificial tables just to inflate table count |
| Azure / Cloud Computing | Azure resource selection, hosting, networking, configuration, cloud service concepts, cost awareness | Provision only what the approved MVP requires; verify student-subscription limits |
| AZ-900 / Azure Fundamentals | Explain cloud service choices, shared responsibility, resource organization, security, reliability/cost tradeoffs where applicable | AZ-900 is a learning/certification framework, not a hosting product or separate application feature |
| AI-900 / AI Fundamentals | Understand AI concepts and explain why the MVP deliberately uses deterministic matching instead of AI | Do not add AI/ML to the MVP solely to demonstrate AI-900 |
| Design Thinking | User problem, student/moderator needs, journey, usability, problem-solution fit, feedback | Do not add features without a user need; retain a simple campus workflow |
| Web Development | Browser UI, REST, forms, validation, sessions/cookies, safe rendering | Keep authorization on backend |
| Computer Networks / Cloud Security | HTTPS, client-server communication, CORS, firewall, identity/access, secure data flows | Security must be part of design, not an afterthought |

## Rubric coverage targets (from project research)

- **System Design:** architecture, component/data-flow diagrams, modular monolith rationale.
- **RDBMS:** normalized schema, keys/constraints, joins, indexes, view, trigger, transaction.
- **DP-900/data fundamentals:** relational Azure SQL, unstructured Blob object storage, analytics.
- **Cloud Security:** authentication, RBAC, HTTPS, secrets, firewall, validation, private file access, audit, threat model.
- **Integration:** React ↔ API ↔ SQL/Blob; SQL analytics ↔ Power BI.
- **Demo/report/viva:** coherent working system, tests/evidence, diagrams, explainable tradeoffs.

## Course mapping policy

1. Use the courses as constraints and learning outcomes, not as an excuse for scope expansion.
2. Prefer one implementation that demonstrates several course concepts naturally.
3. If a course concept is not relevant to the MVP, explain why it is not included rather than forcing it in.
4. The owner will confirm exact curriculum and grading requirements when needed.
