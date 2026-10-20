# ADR-ADMIN-16: Resumable large taxonomy impact previews

- Status: Proposed implementation detail, pending product/API review
- Date: 2026-10-18
- Scope: B2B authoritative taxonomy, Admin BFF, Admin taxonomy UI

## Context

The approved workflow requires large taxonomy backfills to run in batches with resumable checkpoints. The current B2B impact-preview endpoint returned `503 TAXONOMY_IMPACT_ASYNC_REQUIRED` when a subtree or its product set exceeded 5,000 rows, so a large move could never reach review or approval.

The Admin target contract had no job progress resource. This ADR adds the smallest contract extension needed to expose the required background calculation while preserving the current synchronous response for small previews.

## Decision

- B2B owns the durable impact-job record and redirect rows because it owns authoritative category and product data.
- A large preview returns `202` with a stable job ID equal to its `Idempotency-Key`. Reusing the key and request returns the same job; reusing it with a different request returns `409`.
- The Admin BFF exposes an authenticated polling resource. The UI keeps move submission disabled until the job completes and returns the normal, version-bound impact hash.
- A standalone `src.taxonomy_worker` process processes at most 200 category or product rows per transaction. It commits a keyset cursor and counters with each batch, so a process restart resumes from the last committed checkpoint.
- The worker locks taxonomy state for each batch. A changed taxonomy/category version or changed product source causes a terminal fail-closed job; staff must request a new preview.
- Only a completed result is inserted into the existing `taxonomy_impact_previews` table. The existing approval command continues to require and consume that preview hash.
- Small previews remain synchronous. Existing schema migration policy checks remain fail-closed.

## Consequences

- Deployments must run the B2B taxonomy worker separately from API replicas. Compose configurations include that process.
- Large redirect summaries are persisted per category and assembled only when the job completes.
- This job calculates impact and does not mutate taxonomy. The approved move remains an atomic, idempotent B2B command after the maker-checker approval.
- Search/cache projection delivery and rollback reconciliation remain separate acceptance criteria.

## Evidence

Implementation and PostgreSQL evidence: `docs/automation/evidence/admin-taxonomy-impact-job-2026-10-18/REPORT.md`.
