# Changeset: runtime, events and moderation hardening

## Scope

- B2C/B2B cursor pagination and bounded offsets.
- B2B product/SKU deletion notifications persisted through the outbox.
- Admin ticket claim/release/heartbeat with stale-claim TTL and audit logs.
- Strict Admin product-event input validation.
- Production ingress rate limits, read-only containers and one-shot migrations.

## Compatibility

- Existing offset routes remain available with an upper bound of 10,000.
- Legacy Admin product events receive safe defaults for missing idempotency metadata.
- Fake/in-memory test repositories retain direct notification fallback; persistent sessions use outbox.

## Rollback

- Roll back application images while keeping additive migrations (`0003_audit_logs` and existing outbox revisions).
- Do not downgrade or drop audit/outbox tables during an incident; restore or forward-fix after reconciliation.
- Disable new cursor routes at the gateway only if upstream compatibility fails.

## Evidence

- B2B inventory/catalog suites pass.
- B2C catalog/order suites pass.
- Admin moderation, event-schema and lifecycle suites pass.
- Production deployment and compose validation pass.

Operational backup/restore evidence and external SSO/JWKS evidence remain required before a full-production GO decision.
