# Domain model, data ownership and DB constraints

## Bounded contexts

- **B2B/Catalog** — категории, атрибуты, бренды, карточки/версии, SKU, seller identity/reference, public flags, search projection triggers.
- **Admin/Moderation** — immutable review snapshots, tickets, leases, decisions, blocking reasons, appeals, complaints, audit, workflow policy, admin operations and local outbox.
- **Admin/IAM** — staff principal mapping, role grants, MFA evidence/step-up, session metadata; primary identity remains external IdP.
- **B2C/Marketplace** — shopping/buyer orders, feedback/reports, user-facing display projections; Admin does not write B2C tables directly.
- **Media** — object storage, verified image scan/processing and immutable media version references (owner B2B/media service).

Admin reads cross-service data via constrained projections or server-to-server commands, not shared ORM joins across microservice databases. All `*.id` UUID are stable references; product revision is monotone integer in B2B. `external_subject` OIDC string is not forced to UUID.

## Entities (normative fields)

| Entity (owner) | Required fields | Invariants/indexes |
|---|---|---|
| `staff_principals` (Admin) | id UUID, oidc_issuer, oidc_subject, status, created_at | unique `(oidc_issuer,oidc_subject)` |
| `staff_grants` (Admin) | id, principal_id, permission, scope, granted_by, expires_at | no self-grant high privilege, audited |
| `moderation_tickets` (Admin) | id, product_id, seller_id, submitted_revision, snapshot_hash, kind, priority, state, version, created_at, deadline_at | unique `(product_id,submitted_revision,kind)` when appropriate; index `(state,priority,created_at,id)` |
| `moderation_snapshots` (Admin) | id, ticket_id, revision, snapshot JSONB, hash, media refs, policy_version | immutable, FK ticket |
| `moderation_leases` (Admin) | ticket_id PK, owner_staff_id, token_hash, fencing_version, expires_at, last_heartbeat_at | lease at most one owner per ticket, no plaintext token |
| `moderation_decisions` (Admin) | id, ticket_id, revision, actor, action, reason_ids, field_reports, comment, request_hash, idempotency_key, delivery_status, policy_version, created_at | unique `(actor_id,idempotency_key)` scoped, cannot edit/remove |
| `decision_outbox` (Admin) | id, decision_id, aggregate revision, payload, event_id, state, retries, next_retry_at, lease, created_at | unique event_id, durable retry/DLQ |
| `blocking_reasons` (Admin) | id, code, locale labels, severity, applicability, active, policy_version | code immutable, cannot delete referenced reasons |
| `complaints` (Admin) | id, source, reporter_ref, product_ref/seller_ref, category, state, priority, evidence_refs, SLA, created_at | protected reporter, reasoned lifecycle |
| `appeals` (Admin) | id, original_decision_id, claimant_ref, reviewer_staff_id, evidence_refs, state, outcome | reviewer distinct from original actor |
| `audit_events` (Admin) | id, recorded_at, actor, roles, action, entity refs, before_hash, after_hash, reason, request_id, correlation_id, redacted_details, integrity_hash | append-only access; off-site retention |
| `admin_operations` (Admin) | id, type, payload_hash, requested_by, approvals, status, item_results, started_at, finished_at | idempotency + maker-checker |
| `categories` (B2B) | id, parent_id, code, slug, labels, status, sort, path, version, redirect policy, timestamps | no cycles; unique canonical path; no hard delete with refs |
| `attribute_definitions` (B2B) | id, code, data_type, units, constraints, labels, version, status | codes immutable, typed data |
| `category_attribute_rules` (B2B) | id, category_id, attribute_id, required/conditional/variant flags, inherited, version | unique `(category_id,attribute_id,version)` |
| `taxonomy_change_requests` (Admin) | id, target refs, before_version, draft_payload, impact_summary, requested_by, approved_by, status | proposer != approver when sensitive |
| `brands` (B2B) | id, canonical name, aliases, verified status, version | normalized uniqueness, merge history |
| `product_revisions` (B2B) | id, product_id, revision, content, policy_schema_version, status, snapshot_hash, created_at | unique `(product_id,revision)` immutable |
| `product_publications` (B2B) | product_id, published_revision, visibility, visibility_reasons, updated_at | never publish unapproved revision |

## Mandatory database behavior

1. Timestamps UTC (`timestamptz`), no naive datetimes. Foreign keys, check constraints, uniqueness and indexes. Default-deny data exposures via response schemas (never expose raw ORM objects).
2. Each command uses optimistic concurrency (`version` monotonic / If-Match). Moderator claim additionally requires `SELECT ... FOR UPDATE` or atomic compare-and-set. Leases carry fencing sequence to defeat expired-client writes.
3. `decision` creation, audit append, outbox insert and state change in one Admin DB transaction; B2B applies event in separate transaction + inbox receipt in that same transaction. No distributed SQL transaction or direct remote writes before local commit.
4. Snapshot, decision, policy_version and product revision remain queryable for future appeals, including media versions. Redaction/deletion schedules must preserve legal rights and privacy obligations according to policy.
5. Taxonomy move/merge requires impact preflight, transaction-safe subtree update and relationship validation; large backfills run in batches with resumability/cursor checkpoints. Existing slugs redirected safely.
6. Historical stock and payment data never edited as side effect of moderation. Existing orders/returns are handled by explicit fulfillment/refund workflows.
7. Replay duplicate event → same durable result; replay same ID different hash → 409 + incident alert. Out-of-order revision → hold for reconcile, never blindly downgrade publication.
8. Use explicit service DB roles; migration role separate from runtime role. No one service allowed admin privileges over another database.

## Example state machines

### Ticket

`NEW -> IN_REVIEW -> (CHANGES_REQUESTED | DECISION_PENDING | ESCALATED)`; `CHANGES_REQUESTED -> WAITING_SELLER -> NEW` via new immutable revision; `DECISION_PENDING -> DECIDED` only after confirmed downstream projection; any open ticket may become `STALE` on superseding revision and cannot be decided; `ESCALATED -> IN_REVIEW` by appropriately privileged staff. `HARD_BLOCK` is a decision outcome, not the same as temporary visibility `SAFETY_HOLD`.

### Category

`DRAFT -> REVIEW_PENDING -> ACTIVE`; `ACTIVE -> HIDDEN` (hide public listing only with defined product impact); `ACTIVE/HIDDEN -> ARCHIVED` after plan, redirects and product reclassification; `ARCHIVED` not hard-deletable if used in history. New schema versions are immutable after activation. Exposed legacy `is_active` is projection during migration.

### Appeal

`SUBMITTED -> TRIAGED -> IN_REVIEW -> (UPHELD | OVERTURNED | PARTIALLY_UPHELD) -> CLOSED`; appeal outcome generates a new corrective decision/event, not mutation of old record. Two-person for high-risk reversals.

## Representative invariants in SQL form (design examples, not executable migration)

```sql
-- Design intent: reconcile table names with existing Alembic metadata first.
UNIQUE (product_id, submitted_revision, kind);
UNIQUE (oidc_issuer, oidc_subject);
CHECK (version >= 1);
CHECK (lease_expires_at > lease_created_at);
-- transactional command: UPDATE ... WHERE id=:id AND version=:expected_version
-- target rowcount must equal 1, else return 412/409.
```

Detailed expand/contract migration stages in `migrations/MIGRATION_BLUEPRINT.md`.
