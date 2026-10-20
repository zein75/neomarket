# NeoMarket staging backup and restore

**Status:** `NOT RUN`.

No staging databases or object storage were available to the SSH account during S0. A backup target outside the staging host, retention policy, encrypted secret handling, and a restore sandbox must be approved and configured before this gate can be tested. No restore claim is made.

## Runtime update — 2026-10-20

The application runtime is deployed. A fresh isolated local restore drill has now completed for B2C, B2B and Admin: row counts and order-independent checksums matched, and the Admin audit chain remained valid after restore. This proves local logical dump/restore integrity only; no external backup target, WAL/PITR target or approved RPO/RTO is configured, so the staging backup gate remains PARTIAL/NOT READY.

Evidence: `qa-reports/restore-drill/b2b-followup-20261020.json`.
