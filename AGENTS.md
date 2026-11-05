# Coding Agent Instructions — FindMyThing

## Mandatory reading

Before proposing or changing anything, read:

- `README.md`
- `docs/PROJECT_OVERVIEW.md`
- `docs/MVP_SCOPE.md`
- `docs/TECH_STACK.md`
- `docs/COURSE_ALIGNMENT.md`
- `docs/DECISIONS.md`
- `docs/ARCHITECTURE.md`
- `docs/BLUEPRINT.md`
- `docs/IMPLEMENTATION_READINESS_AUDIT.md`
- `docs/IMPLEMENTATION_CONTRACTS.md`

## Current phase: specification closed; implementation not yet started

Architecture, Tech Stack, Blueprint, Decision Register, and Implementation Contracts are frozen. Do not reopen them or change frozen behavior without explicit owner approval.

**Do not start coding, create an application scaffold, or deploy until the owner explicitly authorizes implementation.** When implementation is authorized, follow the frozen documents and begin with the task the owner specifies.

## Authority and conflict resolution

1. Explicit, latest instructions from the project owner.
2. `docs/DECISIONS.md` for frozen project-level choices and scope.
3. `docs/IMPLEMENTATION_CONTRACTS.md` for detailed API, schema, security, validation, operations, and test contracts (provided it does not violate a higher-level frozen decision).
4. `docs/BLUEPRINT.md` for workflows and requirements not superseded by the implementation contract.
5. `docs/TECH_STACK.md` for technology choices and `docs/ARCHITECTURE.md` for component boundaries.
6. Agent suggestions, which are proposals only.

If frozen documents conflict or an implementation detail genuinely cannot be derived, stop and report the conflict. Do not silently change frozen decisions. The audit file records the gaps found before closure. `docs/IMPLEMENTATION_CONTRACTS.md` records the selected resolutions and now governs implementation details. If a conflict remains between approved docs, stop and report it; do not invent policy.

## Project constraints

- Keep the application a small modular monolith unless the owner explicitly approves a change.
- Prefer understandable, demonstrable solutions over novelty.
- Do not add AI, computer vision, vector search, chat, notifications, a mobile app, microservices, Kubernetes, Kafka, Redis, or payments to the agreed project.
- Do not assume Azure services, quotas, or costs are available without checking the owner's actual subscription before provisioning.
- Never commit secrets, real credentials, real student data, or sensitive claim evidence.
- Do not claim that a feature, test, deployment, or Azure resource exists unless verified.

## Expected behavior when implementation is authorized

- Work from approved Architecture, Blueprint, and Implementation Contracts. The Implementation Contracts document is mandatory and resolves detailed implementation choices.
- Make changes in small, reviewable increments.
- Explain assumptions and report blockers.
- Add tests for behavior and authorization as required by approved plans.
- Do not push commits or deploy without explicit instruction.
