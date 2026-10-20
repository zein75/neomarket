# API semantics, event contracts and failure behavior

## HTTP contract rules

- Base `/admin/v1` only for principal-bound clients; `/internal/v1` for signed services. Admin frontend always calls BFF; BFF calls Admin/B2B server-to-server.
- For mutating requests `Idempotency-Key` (UUID string) and `If-Match` where concurrency matters; return `409 IDEMPOTENCY_CONFLICT` on same key with different normalized payload.
- `202 Accepted` contains `{operation_id,status,resource_id?,request_id}`; it does NOT imply downstream publication success. Poll status endpoint or subscribe to authorised server event stream.
- Canonical JSON error `application/problem+json`: `type, title, status, detail, code, instance, request_id, retryable, errors?` (errors field redacted). Invalid input 422; stale ETag 412; conflict 409; anonymous 401; unauthorised 403; dependency 503; temporary limits 429 (+ Retry-After). Never 200 with `{success:false}` for real failures.
- W9 actions that require reporter, claimant or seller notice must return `503 NOTICE_DELIVERY_NOT_CONFIGURED` without writing a decision until a recipient-scoped delivery service is configured. Complaint/appeal evidence responses report `scan_status: NOT_CONFIGURED`; this status is not evidence of a clean scan.
- `GET /admin/v1/settings/integrations` is a configuration inventory, not a health probe: `CONFIGURED_UNVERIFIED` confirms only that required settings are present. It returns no secrets and requires `settings.read`.
- `GET /admin/v1/settings` reports non-secret effective queue/workflow values with `environment` provenance and `CONFIGURED_UNVERSIONED` status; notification delivery remains `NOT_CONFIGURED`, retention remains `BLOCKED_PENDING_DECISION` pending ADR-ADMIN-10, and all sections are read-only until approved versioned settings exist.
- Lists use keyset encoded opaque cursor with stable order `priority DESC, created_at ASC, id ASC`, filters and signed cursor policy if cursor state contains sensitive info; page max 100. `items,page{next_cursor,has_more}`. Immutable action records are never soft-overwritten.

## Event envelope v1

```json
{
  "event_id": "3b81acdc-5eac-4c18-8d94-a61f47fe99e4",
  "event_type": "product.revision.submitted",
  "event_version": 1,
  "producer": "b2b",
  "aggregate_type": "product",
  "aggregate_id": "9139bf92-a16b-43c5-a0f3-92e98103209a",
  "aggregate_version": 7,
  "occurred_at": "2026-10-16T12:00:00Z",
  "correlation_id": "4c15ac8e-dd61-4806-a1f1-a0cb204188e9",
  "causation_id": null,
  "payload": {
    "product_id": "9139bf92-a16b-43c5-a0f3-92e98103209a",
    "seller_id": "6fa3a884-bce1-4c05-bbc1-4bc26e793a99",
    "revision": 7,
    "snapshot_hash": "sha256:REPLACE_WITH_REAL_HASH",
    "snapshot_ref": "object-ref:revision/7"
  }
}
```

This is a **schema example with placeholders**; not an actual emitted production event. Define real media ref/aggregate authorization contract before rollout. Never dereference untrusted URLs for snapshot_ref.

## Required event types

- `product.revision.submitted.v1` → admin ticket submitted.
- `moderation.decision.recorded.v1` → audit/decision, not public publication.
- `moderation.decision.delivery_requested.v1` → outbound to B2B.
- `product.publication.applied.v1` / `product.publication.rejected.v1` → admin operation resolution.
- `taxonomy.category.created|updated|moved|archived.v1` → cache/index synchronization.
- `taxonomy.schema.published.v1`, `brand.merged.v1`, `seller.restriction.changed.v1`.
- `complaint.created.v1`, `appeal.submitted.v1`, `admin.operation.failed.v1`.

Choose a single exact naming convention in an ADR before implementation and don't silently mix dotted names with underscore legacy event types; introduce adapters only at the edge.

### `brand.merged.v1`

- B2B is the producer and brand registry authority. The aggregate is the merged source brand; `aggregate_version` and payload `source_version` are its post-merge version. `correlation_id` and `causation_id` identify the accepted merge command.
- Payload contains `source_brand_id`, `target_brand_id`, post-merge `source_version` and `target_version`, `taxonomy_version`, `product_references_moved`, and the preview `impact_hash`. It excludes product and seller PII.
- B2B writes the event to its transactional B2C outbox in the same transaction as product-reference movement and merge history. B2C stores the event ID plus canonical payload hash in its inbox; a same-hash replay is acknowledged, while a conflicting replay returns 409.
- B2C reads canonical product/brand references through B2B rather than a local materialized catalog. This event does not imply search-index refresh: no search projection is configured in this repository, so that integration remains an explicit gap.

## Consumer contract

1. Validate signature/service identity, schema/event_version, timestamp window where applicable, aggregate ID and monotone version.
2. Calculate canonical payload hash. Insert inbox receipt `event_id` unique in the **same transaction** as business mutation. On duplicate with same hash, return previous response. On same event_id different hash, conflict+alert. On out-of-order event, buffer/reconcile and never roll back aggregate version.
3. Make outbox delivery at-least-once; worker may retry after crash. No optimistic `SENT` without verified HTTP ack.
4. Backoff+jitter; bounded attempts; DLQ with explicit policy and operator case. Manual retry permission-gated and audited.
5. Reconciliation periodically verifies Admin decisions versus B2B published_revision and B2C public projection, and resolves discrepancies with reversible remediation.

## Versioned runtime settings

- `GET /admin/v1/settings` returns effective queue/workflow values with database policy version or environment provenance. Secrets and deployment-controlled worker topology are excluded from writeable policy payloads.
- `POST /admin/v1/settings/{section}/versions` requires `settings.write`, idempotency key, a current base version and a stable reason code. Queue and workflow settings are validated against supported fields and runtime safety bounds.
- A proposal is a `POLICY_CREATE` operation and requires a different `policy.write` approver. Publishing through `/admin/v1/policies/{policy_id}/publish` requires a separately approved publication and rechecks the base version. Published policies take effect in Admin session expiry, step-up age, moderation claim lease, complaint deadline and outbox polling.
- Moderation SLA remains read-only under ADR-ADMIN-13; safety-hold duration remains blocked/unversioned pending ADR-ADMIN-09; retention remains blocked pending ADR-ADMIN-10.

## Product safety holds

- `POST /admin/v1/products/{product_id}/safety-hold` returns `503 SAFETY_HOLD_POLICY_NOT_CONFIGURED` without recording an operation when the approved maximum duration is absent.
- Holds at or below the configured maximum enter the transactional command outbox. Longer holds remain `WAITING_APPROVAL` until an independent staff member with `products.safety_hold` approves them.
- Approval rechecks that the configured limit is unchanged and that the hold expiry is still in the future. Expired or policy-changed proposals cannot be dispatched and must be re-proposed.
- These rules implement the operation flow; they do not resolve the policy value or its approval owner. That value remains blocked until ADR-ADMIN-09 is decided.

## Moderation publication result back to Admin

B2B must emit one of `product.publication.applied.v1` or `product.publication.rejected.v1` after it has durably processed an Admin moderation decision. A successful HTTP `202` from Admin to B2B means only that B2B accepted the command; Admin keeps the ticket in `DECISION_PENDING` until this result event is consumed.

The result uses `EventEnvelopeV1` with `producer: "b2b"`, `aggregate_type: "product"`, `aggregate_id` equal to the product ID, and `correlation_id` equal to the original decision idempotency key. For an applied event, `aggregate_version` equals the reviewed submitted revision. For a rejected event caused by a concurrent product edit, it is the current B2B product revision and cannot precede `submitted_revision`. Its payload contains `decision_id`, `product_id`, `submitted_revision`, `action`, `published_revision` (nullable), `visible` (nullable), and `reason_code` (required for rejection). `decision_id` is the Admin decision/outbox ID. `event_id` is a separate stable UUID for this result event.

B2B writes the result to its transactional outbox with the decision/revision mutation. Admin consumes it at `POST /internal/v1/events/products`, validates it against the immutable decision receipt and outbox payload, then updates the ticket and delivery receipt in one Admin transaction. Same `event_id` and same hash is an idempotent replay; same ID with a different hash is a conflict. Admin never infers publication success from command acceptance or a missing result event.

## Contract verification

- Generate admin/b2b/b2c OpenAPI from actual apps, compare to target, validate examples with JSON Schema/OpenAPI in CI.
- Consumer-driven tests for receipt/replay/version ordering/correlation and redaction; do not treat this document's proposed examples as current runtime behavior.
