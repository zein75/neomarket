# 05 — Transactional outbox/inbox, упорядочивание и модерация

## EVT-001. Единый контракт

Machine-readable `contracts/event-envelope-v1.schema.json`: `schema_version=1`, `event_id` UUID stable across retries, `event_type`, `producer`, `aggregate_type`, `aggregate_id`, `aggregate_version>=1`, `occurred_at` RFC3339 UTC, `correlation_id`, nullable `causation_id`, typed `payload`. Event id and customer idempotency key are distinct. `contracts/product-event-v1.schema.json` and `contracts/moderation-event-v1.schema.json` define exact producer/consumer payload.

- B2B -> Admin: `product.created | product.updated | product.deleted`, `payload.product_id`, `seller_id`, `revision`, `deleted`, product+SKU snapshot. Admin cannot look for `event['product_id']` at top level. On created event, it **must** create a moderation ticket; silently IGNORED is a defect.
- Admin -> B2B: `moderation.approved | moderation.blocked | moderation.hard_blocked`, ticket/decision_id, `reviewed_revision`, verified `actor_id`, reason.
- B2B -> B2C: `catalog.visibility_changed | catalog.sku_changed` with aggregate version; B2B source of truth for published status. Internal inventory events for reconciliation; B2C order status events optional for read models.

## EVT-002. Producer outbox

**One local DB transaction** commits business rows + outbox event, never an HTTP call before local commit. Outbox: event_id PK, event_type, destination, payload, sha256, aggregate/version, status PENDING|LEASED|RETRY|SENT|DEAD, attempts, `next_retry_at`, lease_owner/until/token, error code and times.

Dedicated worker(s) `SELECT ... FOR UPDATE SKIP LOCKED` claim batch and persist lease. Sends scoped mTLS+bearer request. 2xx durable receipt -> SENT; timeout/5xx unknown -> RETRY same event_id; 429 Retry-After; 401/403 -> config/security incident; invalid permanent schema -> DEAD with alert, no silent discard. Backoff capped (initial e.g. 2^n sec, max 15 min ±jitter); dead-letter after e.g. 12 attempts with manual replay privileges. 2+ workers safe. On lost acknowledgment, consumer might have succeeded — publisher must retry **unchanged** event ID/payload.

## EVT-003. Consumer inbox & ordering

Consumer first validates service principal, event JSON schema and version; single `BEGIN` inserts unique `(producer,event_id)` with SHA-256. Same ID+hash -> prior 200 and no mutation; same ID+changed payload -> 409 `EVENT_ID_CONFLICT` and security log. Consumer domain mutation, inbox receipt, and any response outbox are committed atomically. 2xx only AFTER DB commit. Network at-least-once, domain effects effectively once.

B2B product revisions monotonically grow on all publish-relevant edits; Admin stores `last_source_revision`. `aggregate_version<=current` -> stale safe ack (must not revert state), `==current+1` -> apply, `>current+1` -> parked `WAITING_GAP`, request authoritative versioned snapshot; delete tombstone stops resurrection. Admin decision scoped to `reviewed_revision`: B2B rejects stale moderation decision without making product sellable and creates new review task. B2C projection version check same rules.

## MOD-001. Queue and decisions

On first valid `product.created` (real B2B serialized payload), Admin stores immutable product/SKU snapshot and ticket `PENDING` keyed by `(product_id,revision,kind)`. On edit: previous undecided revision becomes SUPERSEDED, new ticket PENDING. On deleted: close tasks, block visibility of product. Ticket state: `PENDING→IN_REVIEW→APPROVED/BLOCKED/HARD_BLOCKED`; `IN_REVIEW→PENDING` on release/expired lease; either -> SUPERSEDED by new revision. Hard block terminal pending privileged appeal workflow.

Claim `SELECT FOR UPDATE SKIP LOCKED`, set moderator verified user + lease expiry + fencing_token, unique active claim. Decision requires active owner+unexpired lease+current version, privilege by role, audit reason, full snapshot; stale token -> 409. Decision commit includes ticket status, immutable decision/audit row, outbound event in same transaction. Because B2B apply is asynchronous, response 202 `DECISION_PENDING_APPLY`; UI displays applied_at and any conflict/lag. Approve must **not** publish SKU before B2B revision-matched apply. Blocked/deleted immediately fail B2B inventory reserve sellability check even if B2C projection lags (B2B final truth).

## MOD-002. Security and audit

Admin SSO/OIDC MFA, real active moderator DB identity, role/scope and object-level checks. Header `X-Moderator-Id` never authenticates. Admin action append-only log of actor, scope, target, before/after digests, reason, correlation_id, timestamp. Runtime DB role cannot UPDATE/DELETE historical audit; export/retention protected; break-glass privilege audited separately.

## EVT-004. Reconciliation & monitoring

- Worker metrics: oldest pending event age, backlog count, attempts/DEAD, throughput, lease expired, 401/403, aggregate gaps; poison messages never starve healthy aggregates.
- Every 5min compare Admin last_source_revision and B2B latest revision, B2B publish state vs B2C projection, pending decisions and inbox receipts. Manual replay uses same event_id only after root cause approval, with audit.
- Outbox/inbox retention cannot be shorter than replay horizon or aggregate version/tombstone memory. Never clean old processed_event and allow duplicate business side effect.

## EVT-005. Required tests

EVT-T01 real B2B producer bytes -> persisted Admin ticket (fix KeyError); EVT-T02 Admin decision -> B2B revision gated; EVT-T03 duplicate after lost ack; EVT-T04 remote side effect never if local rollback; EVT-T05 event ID collision; EVT-T06 out-of-order 1,3,2; EVT-T07 delete then stale edit; EVT-T08 stolen/stale moderator claim; EVT-T09 claim/queue/release; EVT-T10 poison DLQ; EVT-T11 seller→approved→B2C E2E; EVT-T12 block product and test new reserve rejected.
