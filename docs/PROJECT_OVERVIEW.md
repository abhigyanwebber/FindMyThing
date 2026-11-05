# Project Overview

## 1. Project identity

**Name:** FindMyThing  
**Full title:** Secure Campus Lost & Found & Item Recovery Platform  
**Type:** University full-stack/cloud/security/database project

## 2. Problem

On a campus, lost belongings and found items are often communicated through informal channels or handled inconsistently. Students may not know whether an item has been found, while moderators need a reliable process to verify ownership and record recovery.

FindMyThing provides a centralized workflow for reporting, matching, claiming, reviewing, and recovering campus items.

## 3. Intended users

### Student

A student can:

- register, log in, and log out;
- submit lost-item and found-item reports;
- browse and filter eligible reports;
- view potential matches;
- submit a claim for a found item;
- view their own claims and relevant status updates.

### Moderator

A moderator can:

- review and moderate reports;
- review claims and claimant-provided evidence;
- approve or reject claims;
- record successful recovery;
- review relevant activity/audit records;
- access operational analytics.

Authorization must be enforced by the backend. Hiding UI controls is not security.

## 4. Main user outcome

A student reports a lost item or a found item. The system can show a possible counterpart based on transparent, deterministic criteria. A student may submit a claim. A moderator verifies the claim and records recovery. The system preserves the workflow and audit trail.

A match is only a **potential match**. It is not proof of ownership.

## 5. Project goals

- Deliver a working, understandable full-stack application.
- Demonstrate system design and modular separation of responsibilities.
- Demonstrate relational database design and implementation.
- Demonstrate Azure cloud and data fundamentals.
- Demonstrate practical cloud security controls.
- Integrate the frontend, API, database, file storage, and analytics.
- Produce a clear, defensible university demo and viva explanation.

## 6. Design principle

Maximize marks and demonstrable learning per unit of implementation effort and technical risk. Use a deliberately small system. Avoid infrastructure or features that do not serve the approved MVP or rubric.

## 7. Project lifecycle

1. Research and course-informed planning — complete.
2. Architecture, Tech Stack, Blueprint, and Implementation Contracts — frozen specification.
3. Implementation — not started; requires separate explicit owner authorization.
4. Testing, deployment, demonstration, and final documentation — pending implementation and owner authorization.

## 8. Source basis

This overview is based on the project research report, **“FindMyThing — Secure Campus Lost & Found & Item Recovery Platform: Technical Research, Feasibility Investigation, and Decision Specification”**, and the decisions subsequently confirmed by the project owner in conversation. The research report should remain available to the owner as a source reference; it is not a substitute for the approved Architecture or Blueprint.
