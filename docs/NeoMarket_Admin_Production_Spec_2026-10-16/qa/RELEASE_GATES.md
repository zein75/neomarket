# Strict iteration gates / release acceptance

## Definitions

- `PASS` ONLY when scenario executed with correct environment, assertion and artifact; `BLOCKED` for absent IdP/payment/infra; `NOT_RUN` for unexecuted test; `FAIL` for violation. No blank/null treated as pass.
- A test relying on mock services validates local logic, NOT real B2B→Admin→B2C integration. Maintain separate fixture/unit, integration, staging tiers.
- Every requirement ID has owner, source, path(s), test_id(s), evidence link, status, execution timestamp and revision.

## Gate G0 — Current source and specification

PASS if current repo is clean/understood, API schema diff is captured, actual docs/stitch HTML/PNG identified, business constraints documented (privacy, category taxonomy status, banned-content policy, seller KYC, appeals). P0 findings have owner/action. Existing dirty changes preserved.

## G1 — Identity / security

Real OIDC login/logout/callback/refresh/revocation with MFA and string `sub` mapping; all high-risk roles/ABAC denied by default; step-up; API negative tests; CSRF, CSP enforcing, IDOR controls, no production bypass; admin route not visible unauthenticated; unique test principal with least privilege.

## G2 — Moderation integrity

Snapshot version pinned, lease/fencing/claim_token verified, `Idempotency-Key` replay hash semantics, B2B exact product-revision CAS, transactional audit/outbox, inbox/ack and public projection correctness. Concurrency test at least 2 moderators and mid-review seller edit; lost ack and retry scenarios prove no phantom publication; hard-block requires correct permissions.

## G3 — Taxonomy quality

CRUD, localized names, tree move/cycle refusal, attr rules typed validation/inheritance, archive referenced blocked or migration plan, dry-run impacted products correct, import/export safe, approvals and versioning, B2B authoritative state and B2C public projection convergence. No hard delete of referenced category.

## G4 — Admin functional UI

All required routes have real API data and working controls, search/cursors/form states, audit timeline, category and moderation flows. Reproduce reference Stitch composition on desktop. Mobile/tablet adaptations approved when no original baseline. No mock metrics, demo images, fake controls or forced-success status.

## G5 — Adjacent admin modules

Seller compliance, complaints, appeals, reasons, brands, bulk ops, operations, audit, staff roles fully scoped and tested. If outside agreed initial release, remove or mark unavailable **and change launch scope explicitly**; cannot claim full-feature marketplace admin with these mandatory requirements blocked.

## G6 — Resilience and recovery

PostgreSQL + real service integration, outbox worker crash/restart and duplicate event, ordering and DLQ, delayed ack, event redelivery, search/cache reconciliation, migration rehearsals, backup restore from offsite, audit integrity test, load test with large queue and taxonomy subtree. SLO/alerts and runbook exercise.

## G7 — Full quality

- ESLint/TypeScript strict, Python lint+types where configured, unit tests PASS.
- No unverified API contract changes, no high/critical SCA scan findings without signed acceptance; private test data.
- Playwright route+role+workflow+error+visual+accessibility tests PASS; three **independent** clean runs after latest code change; no skipped/flaky/uncounted mandatory scenario; screenshot expected baselines immutable unless human-approved.
- Release docs include exact commit SHA, environment, screenshots, traces, logs, migration report, risk status, reviewer and deployment instructions.
- No P0/P1 known issues; unresolved P2/P3 documented explicitly with owners/timeframes where launch policy permits.

## Staging and prod topology

GitHub Actions builds/test externally. Staging hosts services behind private/TLS gateway and real PostgreSQL/Redis plus OIDC test IdP; cannot claim staging performance on VPS 1vCPU/1GiB. Real prod launch requires measured sizing, isolated secrets, backup/restore tests, failure drills, qualified manual approval. Live prod mutations are never run by generic UI QA automation.

## Evidence manifest example

```json
{
  "requirement_id": "MOD-APPROVE-001",
  "test_id": "E2E-MOD-APPROVE",
  "status": "PASS",
  "commit_sha": "<real SHA>",
  "environment": "isolated-staging",
  "executed_at": "<real ISO-8601 timestamp>",
  "evidence": ["qa-reports/run-001/report.html", "qa-reports/run-001/trace.zip"],
  "verified_by": "CI"
}
```

Never populate the example with invented success results; use only actual CI output.
