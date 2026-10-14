# 07 — PostgreSQL, миграции без потери данных и обслуживание

## DB-001. База данных — граница атомарности

Все доменные операции и соответствующие записи `outbox_events`, `inbox_events`, `audit` либо `inventory_ledger` в пределах **одного** owning DB commit. Изоляция READ COMMITTED с documented row locks; no implicit auto commit в nested repositories, единый transaction boundary в service layer, HTTP remote calls outside transactions. Транзакция должна быть короткой (не ждать сеть/платежи).

- PostgreSQL выделенная поддерживаемая версия, у каждого сервиса отдельные DB+runtime/migrator/readonly учетные роли, TLS, pool budget. Названия всех миграций/версий сохраняются в release manifest.
- По БД: `statement_timeout` default 10s для request traffic (исключения явно заданы), `lock_timeout` default 2s, `idle_in_transaction_session_timeout` default 15s, `pool_pre_ping`, `max_overflow`, `pool_timeout`; реальные значения после нагрузочных измерений. Job transaction может иметь отдельный timeout.
- Все таблицы с timestamp UTC, server_default NOW() с tz-aware, immutable IDs UUID, целые суммы `BIGINT`/`NUMERIC(20,0)`. Никаких `float` для денег, миграционные преобразования из `Integer` с проверкой диапазона.

## DB-002. Обязательные изменения

**B2B:** SKU `price_minor`, `on_hand`, `reserved`, CHECK nonneg+reserved<=on_hand; `inventory_order_lifecycle` с PK order_id и terminal flags; `reservation_lines` with unique order+sku+state; `inventory_ledger` append only; `stock_adjustments`; product revision; unified outbox with lock metadata; normalized inbox+dedup. Доработать индексы `(status,next_retry_at,lease_until)`, `(sku_id,state)`, `(product_id,revision)`.

**B2C:** checkout_intents c durable lease/fencing, request hash, unique `(buyer_id,idempotency_key)`; orders with version and stable amount fields; cancel_jobs and fulfillment_jobs with retry metadata; processed events with content hash; status_history immutable; cart qty CHECK > 0; quote snapshot; account sessions/revocations; audit of sensitive operator actions.

**Admin:** moderation_tickets keyed `(product_id,revision,kind)`, SKU snapshots/version, claim lease/fencing, decision history, outbox/inbox, audit_events append only, moderator accounts bound to SSO subject. Unique active claim semantics and active ticket constraint (use conditional partial index if possible), index queue priority/created_at.

**Cross-cutting:** DB indexes supporting request patterns and workers, retention job table, schema migration history, keys for event ledger, no app writes as DB superuser.

## DB-003. Expand/migrate/contract без блокировки

1. **Inventory existing data preflight**: before any DDL, run SELECT-only checks for negative stock/price, reserved > stock, duplicate `(order_id,sku_id)`, active reservation quantity mismatch, orphan `order_id`, malformed UUID/key/JSON events, orders with cancel_pending > threshold, terminal orders still reserving, invalid moderators. Save signed reports.
2. **Safety**: freeze risky legacy endpoints, verify tested PITR and encrypted offsite backup, dedicated rollback snapshot, approve maintenance and communication; take metrics baseline.
3. **Expand**: add nullable/parallel new columns/tables/indexes `CONCURRENTLY` where supported (outside transaction as required), triggers only if independently justified and reviewed; do not drop existing columns.
4. **Backfill**: batches of e.g. 1000 rows (configurable), keyset paging with checkpoints, updates with idempotent run IDs, bounded lock time, monitor WAL/bloat/replica lag. Never backfill live reserved state from unreliable duplicated operations without business reconciliation.
5. **Dual-compatible deployment**: new code reads old/new or dual-writes where necessary; dual-write done in a single transaction, read compare logs; outbox producer changes behind versioned flags.
6. **Validate**: `CHECK NOT VALID` then `VALIDATE CONSTRAINT`, FK migration verify, new unique indexes and query plans; run concurrent E2E, staged original dataset anonymized copy.
7. **Switch**: enable new endpoints/worker gradually, compare invariants, ensure monitoring; turn off legacy endpoints and serializers; verify canary.
8. **Contract**: after documented compatibility window and rollback window, remove old columns/routes in separate migration. No `DROP` with active consumers.

**Важно:** `db/SCHEMA_BLUEPRINT.sql` — schema proposal, его нельзя исполнять на существующей БД напрямую. Каждое изменение создаётся отдельной Alembic revision с specific preflight, forward and app-level rollback notes, migration owner and migration SQL reviewed.

## DB-004. Rollback и несовместимость

- Code rollback возможно только если schema still backwards-compatible; миграции forward-only by default for data-migration steps. Если rollback requires destructive reversion, **не** делать destructive downgrade; fail closed, restore from PITR to staging/recover via documented repair job and incident approval.
- One-shot migration job with exclusive deploy coordination; **никаких Alembic upgrade в CMD каждой API реплики**. Before migrate verify DB endpoint/environment, backup restorable, available disk>=estimated WAL/data, user approval. Validate `alembic current` and post smoke.
- Zero-downtime применим только для изменений со строгим expand/contract. Нельзя обещать безостановочность для специфичных DDL без тестов live-equivalent DB.

## DB-005. Health / retention / backup

- Monitoring: connection saturation, max locks, deadlocks, long txns, replication lag, WAL archiving, disk, slow queries, bloat/vacuum, index scan pattern. Pool sizes across replicas must fit Postgres `max_connections` with headroom for backup/admin.
- Daily job retention: guest sessions/cart cleanup with safe null user, delivered outbox data archiving after retention and compacted tombstones; processed event retention cannot be shorter than retry/replay horizon or aggregate version protection. Never bulk delete active holds/jobs.
- Dedicated index/partition strategy for outbox, logs and order history only after measured growth; large user deletion follows anonymization policy.

## DB-006. Required DB tests

MIG-T01 up/down fresh schema in staging; MIG-T02 migrate anonymized current DB snapshot; MIG-T03 idempotent backfill double-run; MIG-T04 missing/duplicate data preflight FAIL; MIG-T05 no >2sec lock in migrations allowed during active traffic (profile/maintenance-specific); MIG-T06 API old+new binary compatibility through expansion; MIG-T07 crash halfway through backfill and restart; MIG-T08 DB restart/connection cut, SQLSTATE deadlock retry; MIG-T09 FK/CHECK/UNIQUE negative cases; MIG-T10 replication/backups/restore consistency. Publish EXPLAIN ANALYZE on catalog, jobs and owner-scoped queries.
