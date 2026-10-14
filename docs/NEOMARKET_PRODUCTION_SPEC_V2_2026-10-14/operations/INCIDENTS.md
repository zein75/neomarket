# Incident playbook: inventory, orders, auth, event backlog, production outage

**Applies to:** on-call/SRE, security, DBA, product owner; all commands are design-level, should be translated into approved stage-tested tool scripts. Never use destructive tests in production. Never `docker compose down -v` with data.

## Universal response

1. Detect + page on-call, assign incident ID/severity and commander; record start time affected requests and last known consistent point.
2. Protect evidence (audit/outbox/inbox, request IDs, backups) and stop untrusted/unsafe traffic using scoped feature flag / ingress; avoid destroying partial orders.
3. Check readiness, DB storage/WAL, service principal/identity, worker lease and oldest queues. Always favor read-only SELECT queries first.
4. Choose recovery by state machine, use **same** event_id/order_id/request hash for replay; never patch stock directly. Require approved ledger adjustment if fixing data.
5. Verify invariant report and E2E smoke before unfreezing; report impact, owner, remediation, tracked incident follow-up.

## Scenario 1: SKU reserved mismatch / potential oversell

- P0: freeze writes for affected SKU/product; stop stock adjustments and new reserves, do not drop historical reservations.
- Read B2B `skus`, active reservation lines, lifecycle, ledger and B2C order state under consistent snapshot. Identify missing ledger/duplicate order or restore split-brain.
- Repair by audited reversible correction via inventory adjustment tool that takes locks and writes ledger, after security/DBA approval; do not `UPDATE stock=...` ad hoc.
- Run INV-T01/T06/T12 targeted staging repro with captured sanitized sequence. Reconciliation 0 discrepancies and incident-approved unfreeze.

## Scenario 2: Order stuck in `RESERVING`, `CANCEL_PENDING` or `DELIVERY_FINALIZING`

- Verify durable intent, worker lease/fencing and B2B lifecycle by signed read-only endpoint; inspect last remote call/ack.
- If ambiguous reserve, retry same reserve id; if compensation decided, retry `unreserve` with same order_id; `CANCELLED` from B2B -> close B2C; `FULFILLED` -> operator exception/returns, **not** silent cancel.
- Replay only after checking current lifecycle and conflicting worker; same exact key and payload. Manual operator action logged with actor and reason.

## Scenario 3: Event delivery or moderation backlog

- Check outbox worker and DB availability, service credentials, event schema, aggregate_version gap, DLQ. Pause only offending aggregate/event not all healthy work if safe.
- Fix consumer/schema, replay original event_id and version; validate Admin ticket exists and B2B applied decision, B2C catalog projection. Do not manually approve product by changing B2B `is_active`.

## Scenario 4: Auth bypass / compromised credentials

- Security P0: disable affected endpoint/account, rotate/revoke service tokens/keys, isolate network route, preserve access audit, identify timeframe and impacted objects. No broad cleartext logging of victims/tokens. Legal breach notification reviewed by security/legal.
- After fix test 401/403 for wrong identity and replay attacks, manual external surface review before reopening.

## Scenario 5: Backup/WAL/archive compromised / DB lost

- Halt high-risk deploy and write operations as appropriate; notify DBA/incident commander. Preserve latest safe backups (immutable if possible).
- Follow `operations/BACKUP_RESTORE.md` in clean isolated environment. Report actual RPO/RTO, cross-service reconcile, operational validation before promoting recovered instance.
