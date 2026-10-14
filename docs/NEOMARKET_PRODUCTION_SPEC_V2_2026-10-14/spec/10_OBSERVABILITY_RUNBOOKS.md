# 10 — Наблюдаемость, SRE, эксплуатационные процедуры

## OBS-001. Three pillars + audit

- Structured JSON logs: timestamp UTC, level, service, version, region, trace_id, span_id, request_id, principal type, operation_id, `order_id`/`event_id` pseudonymized where possible, error_code, duration_ms, dependency. **Запрет** токенов, cookies, password hashes, raw PII/address, payment card details, secrets, HTTP Authorization.
- Metrics (Prometheus/OpenTelemetry): per-route request latency histogram and counts (`method/path/status`, no arbitrary UUID label), `http_5xx`, `auth_denied`, `db_pool_in_use/wait`, `db_locks/deadlocks`, `outbox_pending/oldest_age`, `inbox_conflicts`, `worker_attempts/dead/retries/lease_expiry`, `checkout_pending/oldest_age`, `cancel_pending`, `fulfillment_pending`, `moderation_pending/stale_decisions`, `inventory_invariant_violations`, `reconcile_diff`, `backup_last_success`, `wal_archive_lag`, `restore_last_verified`.
- Distributed traces with W3C traceparent propagates over service HTTP/outbox; event carries correlation_id, delivery span linked via event ID; asynchronous workflows sampled reasonably, error paths always kept within privacy constraints.
- Immutable admin audit trail and access audit for backups and sensitive operations, secure log retention. Audit not replaced by standard debug logs.

## OBS-002. Readiness, liveness, synthetic checks

`/live`: ASGI process alive (no DB calls). `/ready`: DB and schema reachable, ability to do lightweight SELECT; dependency checks necessary for write/read correctness; distinct worker `/metrics` and heartbeat. Worker dead should trigger alert even when API healthy. External synthetic tests: buyer catalog, seller restricted route, private moderation under synthetic identity (never public), non-mutating DB and API probes. Avoid synthetic checkout in production unless known isolated test accounts and designated non-real inventory.

## OBS-003. Alert policies (initial thresholds, tune against baseline)

| Alert | Condition | Priority | First action |
|---|---|---|---|
| Inventory mismatch | any confirmed SKU discrepancy | P0 | freeze affected SKU writes, page on-call |
| Orders orphan | any durable B2B active reserved without B2C committed/pending intent beyond grace | P0 | reconciliation + no blind release |
| Backup/PITR unsafe | WAL archiving stopped >5m or no verified backups within 24h | P0 | block risky deploy, incident |
| Auth bypass indicators | unscoped internal call success / admin impersonation | P0 | revoke tokens, freeze admin writes |
| Outbox oldest | >120s on critical event or >1000 pending | P1 | inspect worker lease/network/DLQ |
| Checkout/Cancellation stuck | age>5m or counts rapidly increasing | P1 | inspect downstream status/retry, manually reconcile |
| Fulfillment delayed | pending>5m after delivery proof | P1 | verify B2B reachability, rerun same id |
| DB capacity | >80% connections for 5m, disk <20%, long lock >10s | P1 | scale/throttle, query review |
| API SLO burn | sustained 5xx/p95 SLO burn windows | P1 | rollback canary / fail safe |
| DLQ>0 on business-critical event | first confirmed occurrence | P1 | root-cause, manual replay gated |

Escalation: primary on-call acknowledges in <=5 min for P0, secondary in <=10 min, incident commander appointed; escalation mechanism must have out-of-band failure path. Thresholds engineering defaults and require tuning on actual load.

## OBS-004. Operability и support

- All queued jobs show state, attempts, last_safe_error, lease, next_retry_at, last_event_id in protected operator UI. Manual replay only same event/order_id with approval and audit.
- Support view displays B2C Order snapshot, B2B lifecycle read-only, saga state, last successful/event timestamps, no raw secret/PII by default. Investigate by correlation id and immutable audit log.
- Dashboard for availability, dependency, queue lag, stock consistency, moderation SLA, backup status, CPU/memory, storage, DB, users impact, canary release. Each metric has runbook link and responsible team.
- SLO reviews weekly, error budget policy: if exhausted freeze nonessential releases until improved. Every P0/P1 postmortem with repro steps, missing control analysis, owner/date and closing evidence.

## OBS-005. Incident flow

Detection -> classify severity + affected assets -> freeze unsafe write routes if needed -> preserve evidence -> confirm live DB state under read-only credentials -> coordinated recovery/replay -> reconciliation tests -> staged unfreeze -> postmortem. For P0 security compromise revoke secrets and isolate network, do not publicly expose sensitive forensic artifacts. For suspected data loss, never overwrite latest available backups before preserving immutable copy.

## OBS-006. Tests

OBS-T01 failed DB causes /ready 503; OBS-T02 worker silently dies -> alert; OBS-T03 poison outbox gives DLQ+alert and does not starve other events; OBS-T04 2 worker replicas simultaneously claim without duplicate; OBS-T05 incident alert ack routing tested; OBS-T06 logs never emit tokens/PII; OBS-T07 trace correlates checkout reserve/cancel; OBS-T08 reconciliation seeded anomaly detection.
