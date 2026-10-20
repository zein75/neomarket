# ADR-ADMIN-15: Versioned brand merge event envelope

- Status: implementation decision; stakeholder approval still pending.
- Date: 2026-10-18.
- Scope: propagation of an explicitly approved canonical brand merge from B2B to B2C.

## Context

`EVENTS_AND_ERRORS.md` requires a durable `brand.merged.v1` event, an idempotent consumer receipt and an exact event naming convention before implementation. B2B is authoritative for brands and product references. B2C catalog reads currently query B2B directly; no separate search/index service or B2C brand materialized view is configured in this repository.

## Decision

- Emit the dotted event name `brand.merged.v1` from B2B's transactional outbox in the same transaction that moves product references and records `BrandMergeHistory`.
- Use the shared EventEnvelopeV1 fields: producer `b2b`, aggregate type `brand`, source brand ID/version, command ID as correlation and causation ID, and a stable event ID derived from the merge command ID.
- Payload includes source/target brand IDs and versions, taxonomy version, impact hash, and the product-reference count moved. It contains no product or seller PII.
- B2C stores the event ID and canonical payload hash in its existing processed-event inbox. Its catalog is read-through to B2B, so accepted merges are observed from B2B's committed canonical references; no stale local brand cache is introduced.
- Automatic duplicate detection or merge remains disabled. Brand verification remains a separate maker-checker action with evidence reference.

## Consequences and limits

- B2B command replay cannot create a second outbox event; delivery is at-least-once and B2C receipt is idempotent with payload-hash conflict detection.
- B2C currently has no search index/materialized brand projection. This decision does not claim search reindexing; `ADM-018` remains open until a concrete index/projection and reconciliation contract exists.
- Exact event payload and consumer behavior must be verified with isolated PostgreSQL and service-level tests. Keycloak and business stakeholders have not approved the remaining brand verification policy in ADR-ADMIN-12.
