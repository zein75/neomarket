# Последовательность реализации до полного production, по шагам

## Правило исполнения

Каждый шаг: отдельный PR, runnable code+migrations+tests+feature flags+docs; до merge — строгие negative/concurrent tests, no regression по full suite; после — artifact commit SHA and sign-off. Точно изменяемые файлы уточняются с фактической структурой repo; перечисленные ниже — обнаруженные исходные модули из архива. **Никаких устаревших canon/OpenAPI к проверке не привлекать**. Контракты впервые создаются в `contracts` и затем версионируются в самом проекте.

### Этап 0. Immediate quarantine / риск P0

**STEP 0.1** Закрыть из внешней сети postgres/redis/admin и внутренние write endpoints. Разделить dev compose и production manifests; временно закрыть gateway на непроверенные handlers. Изменить `docker-compose.yaml`, `nginx/nginx.conf` (сейчас пуст), `Makefile prod`, IAM/firewall config. Acceptance `SEC-T07`, outside scan. DoD: none DB/admin/service internal accessible from public.

**STEP 0.2** Удалить или вернуть 410 + actual disabled из `services/b2b/src/api/routers/reservations.py` для legacy `/reservations`, `DELETE /reservations/{order_id}`, services methods `ReservationService.create/cancel_by_order` недоступны любому network client. Add unauthorized tests; acceptance SEC-T01/INV-T01. Не достаточно `include_in_schema=False`.

**STEP 0.3** Replace insecure `services/*/src/core/config.py`, JWT validation in `services/b2b/src/core/security.py`, `services/b2c/src/core/security.py`, `services/admin/src/api/deps.py`, `middleware/auth.py`; secret manager + fail-fast, service principals and RBAC. Add private Admin gateway/SSO MFA, no moderator ID spoofing; SEC-T01..08.

**STEP 0.4** DR baseline before touching data: offsite backups/PITR, full restore dry run and documented recovery, secret/key separation; `operations/BACKUP_RESTORE.md`; DR-T01..05.

**Gate 0:** P0-01,02,03,06 mitigated and evidenced; failure means continue work only in isolated staging.

### Этап 1. Database semantics and stock correctness

**STEP 1.1** Existing dataset preflight; add B2B Alembic migrations for `on_hand`, SKU constraints, lifecycle and reservation_lines, ledger and indexes. Files `services/b2b/src/models/sku.py`, `reservation.py`, new `inventory_order_lifecycle.py`, `reservation_line.py`, `inventory_ledger.py`, migrations, `sku_repo.py` and `reservation_repo.py`.

**STEP 1.2** Refactor `services/b2b/src/services/reservation_service.py` to single order_id locked lifecycle, tombstones on unreserve, canonical request fingerprint, sorted SKU locks, no timed deletion of business idem, consistent transaction boundaries; adjust `models/reservation_operation.py`, `unreserve_operation.py`, tests `services/b2b/tests/test_inventory_*.py`. INV-T01..12.

**STEP 1.3** Seller SKU stock update must use same locks/adjustment ledger. `services/b2b/src/services/sku_service.py`, `schemas/sku.py`, routers and DB CHECK. Validation `price>=0`, `stock>=reserved`; server-side image allowlist. SEC-T09, INV-T02/T09.

**Gate 1:** no negative stock, double reservation, late reserve resurrection or missing ledger in randomized PostgreSQL concurrent tests. Reconciliation actual SQL zero discrepancies.

### Этап 2. Durable asynchronous integration

**STEP 2.1** Unified `contracts/event-envelope-v1.schema.json`, `product-event-v1.schema.json`; `services/b2b/src/clients/moderation.py`, Admin moderation handler and Pydantic schemas. Producer->Consumer actual payload tests. EVT-T01 and no KeyError.

**STEP 2.2** B2B/Admin/B2C producer outboxes, consumer inboxes, event schema revision/ordering, retries with leasing, DLQ and per-aggregate versions. Existing `services/b2b/src/models/outbox_event.py`, `repositories/outbox_event_repo.py`, `services/b2b/src/main.py`, `services/b2c/src/main.py`, new worker entrypoints `src/workers/*`, `inbox` models and migrations; move **all** product/moderation/catalog remote writes out of pre-commit service code: `product_service.py`, `sku_service.py`, Admin `moderation_service.py`, clients. EVT-T02..07.

**STEP 2.3** Admin completeness: `services/admin/src/services/moderation_service.py`, `repositories/moderation_repo.py`, models and migrations, currently empty `api/routers/auth.py`, `products.py`, `sellers.py`, `models/audit_log.py`, add ticket CRUD/claim/release/heartbeat/decision, SSO/RBAC and audit. EVT-T08..12. Verify create product→Admin→B2C, edit/delete + delayed events.

**Gate 2:** no lost product event after DB rollback/crash; claims secure, outbox queue drains with 2+ workers; blocked SKU unsellable.

### Этап 3. Order/checkout and fulfillment

**STEP 3.1** B2C checkout intents durable lease/fencing and order status machine. `services/b2c/src/services/order_service.py`, `models/order.py`, `repositories/order_repo.py`, `api/routers/orders.py`, new `checkout_operations` route, migrations. Remove ambiguous final success under timeout; ORD-T01..05.

**STEP 3.2** B2C durable cancellation jobs and B2B tombstone linked to B2C final ack; compensate only if still valid, no creating order after COMPENSATING; same source files/order saga worker. ORD-T06..07.

**STEP 3.3** Authenticated delivery operation and separate fulfill worker; wire existing `retry_pending_fulfillments` to live job scheduler, extend persisted state/backoff, implement `DELIVERY_FINALIZING`; ORD-T08..09. Payment scope per `spec/11`.

**Gate 3:** repeated checkout/order deliveries, cancel and fulfill fault tests no orphan/duplicate; financial mode/logic never fakes PAID.

### Этап 4. Runtime, API, performance, security

**STEP 4.1** Replace old API definitions with `contracts/http-*.openapi.yaml` as new sole contract; implement missing public/owner-scoped endpoints, standardized errors, session lifecycle; CI `openapi diff`. `services/*/src/main.py`, all routers/schemas, shared utilities. API-T01..04.

**STEP 4.2** Move catalog filters into SQL and add indexes, paginate by cursor, load/capacity test. `services/b2b/src/services/product_service.py`, `repositories/product_repo.py`, B2C catalog adapter and migrations. PERF-T01..02.

**STEP 4.3** Harden deploy: nonroot digest-pinned image Dockerfiles, production IaC, ingress TLS, resource limits, no startup migrations, private networking, worker autoscale bounded. `services/{b2b,b2c,admin}/Dockerfile`, CI manifests, `Makefile`, prod IaC. OPS-T01..04.

**STEP 4.4** Metrics/traces/log redaction, readiness, alerts, incident support, data retention, secret rotation; `services/*/src/main.py`, shared middleware, workers/repo and operations runbooks; OBS-T01..08.

**Gate 4:** real environment no public data ports, correct RBAC/HTTP error envelopes, SLO goals load/soak, security scans/pentest, operator alert and DR drill pass.

### Этап 5. Full release and non-code blockers

**STEP 5.1** Validate real product scope: PSP and refunds, logistics, seller payouts, legal policy; if full online marketplace required, implement and certify BUS-T01..03. No external money flow before evidence.

**STEP 5.2** Run all `qa/ACCEPTANCE_TEST_PLAN.md`, live contract diffs, restore to isolated site, rollback drill, 24h soak and 2x load; sign-off `operations/GO_LIVE.md` including evidence links per risk. 1% canary -> 5% -> 25% -> 100%; abort on invariant/security/backup alerts.

**STEP 5.3** Post-launch: continuous reconciliation, SLO reviews, regular restore drills, planned secrets rotation, weekly risk review and incident simulations; no return to unmonitored/untested manual state.

## Recommended sequencing

Implement one step at a time, verify no regression, then proceed; avoid massive rewrite. For each step create `changeset.md` detailing schema effect, backward compatibility, rollback, test IDs, risk IDs, owner, exact CI logs and deployment proof. New paths/modules listed above are **proposed additions**, not assertions that these files already exist.
