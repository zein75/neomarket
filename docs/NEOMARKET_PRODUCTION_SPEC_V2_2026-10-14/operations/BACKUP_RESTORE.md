# Backup/restore operational procedure (runbook template)

**Prerequisite:** chosen PostgreSQL PITR tooling/managed service configured. This is a procedure/checklist, not a magic executable command; actual `pgBackRest`/managed CLI depends on infrastructure and must be staged and reviewed. Never restore into the original production DB before preserving its available state.

## Daily control

- [ ] Check successful basebackup time and checksum, WAL archive continuous status/lag, backup storage size, immutability/object lock, encryption/key availability, offsite account permissions.
- [ ] Check alert for archive gap, backup failure, available disk and PITR retention coverage.
- [ ] Check latest restore drill timestamp and incident follow-up state; SLO dashboard has evidence.

## Monthly clean-room restore

1. Select arbitrary recovery timestamp inside recent retention range and expected committed business operations (order_id, SKU ledger entry, admin event) observed **before** incident simulation.
2. Provision isolated database environment with independent credentials/keys, no customer-facing ingress and no traffic routing. Verify backup manifests/integrity and recovered WAL timeline; restore three logical DB domains.
3. Log `restore_start`, `selected_recovery_point`, `WAL_latest_recovered`, `restore_complete` in UTC; compute actual data age/RPO and elapsed RTO. Do not invent success if lag exceeds target.
4. Run migrations-current and schema integrity read-only checks, critical constraints, cross-service reconcile B2B/B2C/Admin and durable outbox/inbox mismatch review.
5. Run operator read-only synthetic query and controlled mutation of synthetic tenant; assert owner isolation; ensure no external webhook/SMS/PSP side effects sent during drill.
6. Produce signed machine-readable report including failures, corrective backlog, RPO/RTO and next drill due. Delete test environment according to retention policy only after archiving evidence.

## Live disaster recovery

0. Executive/incident commander approves DR move. Freeze writes/PSP outgoing integrations; export untouched source state if available, preserve evidence.
1. Choose recovery point **based on business data consistency**, not only newest WAL; note cross-domain timeline gaps. Provision secure target and restore/backfill WAL.
2. Recover B2B then B2C/Admin or independent parallel restore with coordinated interface freeze. Before any replay, validate unique lifecycle ID, order status, product revision, and ledger totals.
3. Reconcile missing/in-flight orders, reserve/unreserve, fulfillment, moderation events using exact event IDs and signed service calls, not direct SQL side effects.
4. Validate auth/secrets and DB grants; rotate compromised keys; verify endpoint network isolation.
5. Canary write for designated synthetic/test tenant with available test SKU and no real payment; if invariants pass, controlled progressive traffic restoration.
6. Record actual time, impact, unresolved exceptions, permanent fixes and trigger next full test; confirm on-call/product/security sign-off.

## Critical failure cases

No valid offsite backup, no required WAL timeline, failed data checks, misaligned replay semantics or unknown stock ledger -> NO-GO; do not re-enable write traffic. Escalate to DBA/security/product for approved manual recovery.
