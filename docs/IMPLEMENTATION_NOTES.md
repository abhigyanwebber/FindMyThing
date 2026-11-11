# Implementation Notes: Discrepancies, Assumptions, Decisions

Companion to `IMPLEMENTATION_STATUS.md`. Records every place the implementation had to resolve a
spec problem or fill an unspecified detail. Precedence follows `AGENTS.md`
(`IMPLEMENTATION_CONTRACTS.md` governs).

## Discrepancies found and resolved

### N-001: Computed guard columns cannot back filtered unique indexes (SQL Server error 10609)

- **Spec:** Contract §6/§26 require persisted computed guard columns
  (`active_claimant_found_guard`, `active_found_guard`, `active_lost_guard`) with a unique
  index filtered `WHERE guard IS NOT NULL`.
- **Reality (verified on SQL Server 2022):** `CREATE UNIQUE INDEX ... WHERE <computed column> IS NOT NULL`
  fails with *"the column ... in the filter expression is a computed column"* (10609). The design
  as written cannot be created.
- **Contract's own rationale:** the guard columns exist only for the case where "a filtered
  predicate cannot directly represent the status set". An `IN (...)` predicate on the real columns
  can, and was verified to work.
- **Resolution:** direct filtered unique indexes on base columns, no computed columns:
  - `ux_claims_active_claimant_found (claimant_user_id, found_report_id) WHERE status IN ('PENDING','VERIFIED')`
  - `ux_claims_active_found (found_report_id) WHERE status IN ('VERIFIED','RECOVERED')`
  - `ux_claims_active_lost (lost_report_id) WHERE status IN ('VERIFIED','RECOVERED') AND lost_report_id IS NOT NULL`
- **Invariants preserved:** identical to the contract (many PENDING per FOUND; one active claim per
  claimant/FOUND; one VERIFIED/RECOVERED per FOUND and per LOST). Covered by `tests/test_schema_sql.py`
  on real SQL Server.

## Assumptions (spec silent)

- **A-001 Matching arithmetic:** factor scores and total use `Decimal`, quantized to 2 places
  (ROUND_HALF_UP) to match `decimal(5,2)`. The 50-point threshold is applied to the quantized total
  so a stored score and stored status can never disagree. Threshold is inclusive.
- **A-002 Stopwords:** fixed English list in `app/domain/matching.py`. Changing it requires a new
  `algorithm_version`.
- **A-003 Trigger fallback:** if the application forgets to set trigger context, the trigger still
  writes history with `reason_code='UNSPECIFIED'`, `correlation_id='none'`, actor NULL (safety net;
  the application always sets context).
- **A-004 Analytics views:** `vw_recovery_analytics` and `vw_claim_transition_analytics` expose
  categories, locations, timing and counts only. No claimant identity, statements, evidence or
  blob keys (asserted by test).

### N-002: Moderator correction of terminal reports (contract §2 vs §4.2)

- **Conflict:** §2 says moderator correction is allowed "only while report is ACTIVE"; §4.2 (the route
  contract) and Blueprint §19 say it is allowed for ACTIVE **and terminal** reports.
- **Resolution:** follow §4.2/Blueprint (the route-specific, later, and more detailed text). Terminal
  corrections invalidate matches but never enqueue matching or change status. Covered by a test.

### N-003: Image output format (contract §9 vs §21)

- **Conflict:** §9 says normalize photos to JPEG unless transparent; §21 says re-encode to the *same*
  allowed source format (JPEG→JPEG, PNG→PNG, WebP→WebP).
- **Resolution:** follow §21 (later "Remaining operational constants", more specific). Metadata is
  stripped by re-encoding in every case. Implemented in the upload service.

## Additional assumptions

- **A-005 Reference data route:** the contract has no taxonomy endpoint; `GET /api/reference-data`
  (authenticated, read-only, active rows only) was added so the frontend can build forms and filters.
- **A-006 Dismiss response shape:** `POST .../dismiss` returns "match shape" without a counterpart
  (the moderator is not viewing from one report's side): `{match_id, lost_report_id, found_report_id,
  score, factors, explanation, calculated_at_utc, algorithm_version, match_status}`.
- **A-007 Competing claims on recovery:** only other PENDING claims on the *same FOUND report* are
  auto-rejected. A PENDING claim on a different FOUND report that links the now-RESOLVED LOST report
  stays PENDING; verifying it fails with 409 (LOST must be ACTIVE) and a moderator rejects it.
- **A-008 Claim creation history:** no `claim_status_history` row is written at submission; history
  records transitions only (`created_at_utc` is the submission time). Avoids inventing a reason code.
- **A-009 Only students create reports and claims:** moderators moderate; they cannot create reports
  or claims (also removes conflict-of-interest cases).
- **A-010 Search:** `q` uses parameterized `LIKE` with escaped wildcards, all terms required, over
  title and description. SQL Server `CONTAINS` needs a full-text catalog, which adds deployment
  surface for no behavioural gain at campus scale. Can be swapped for full-text later.
- **A-011 CSRF token rotation:** only the token hash is stored, so `GET /api/auth/csrf` issues a fresh
  token and invalidates the previous one. The frontend refetches and retries once on `CSRF_INVALID`.
- **A-012 Lock ordering:** ascending order uses the canonical lowercase UUID string, applied
  consistently across workflows (SQL Server's own `uniqueidentifier` sort order differs; only
  consistency matters for deadlock avoidance). Each row is locked in its own statement.
- **A-013 Matching poller:** an in-process daemon thread polls due jobs (`MATCHING_WORKER_ENABLED`,
  default on). Jobs are durable in SQL, leases are multi-instance safe (`READPAST`), and a CLI command
  can also run them.