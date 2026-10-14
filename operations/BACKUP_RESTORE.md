# NeoMarket backup and restore runbook

This runbook is a gate for production changes. It does not claim that PITR is configured; the infrastructure owner must attach provider evidence before a go-live approval.

## Preflight

- [ ] Verify encrypted off-site PostgreSQL base backups and continuous WAL archiving for B2B, B2C and Admin.
- [ ] Verify backup credentials are held outside the repository and can be revoked independently.
- [ ] Confirm the latest backup manifest/checksum and archive lag are within the approved RPO (target: 5 minutes).
- [ ] Freeze risky writes and record the selected UTC recovery point.

## Clean-room restore

1. Provision isolated databases with independent credentials and no public ingress.
2. Restore the three databases to the selected PITR using the managed provider or pgBackRest procedure.
3. Run each service's Alembic migrations in the one-shot migration jobs from `docker-compose.prod.yaml`.
4. Start services in read-only validation mode and check `/ready` plus inventory/order/moderation invariants.
5. Reconcile B2B reservation lifecycle and ledger against B2C orders; record missing, duplicate or split-brain IDs.
6. Record `restore_start`, recovery point, latest recovered WAL, `restore_complete`, measured RPO and RTO.

Never restore over the original production database before preserving its state and obtaining incident approval.
