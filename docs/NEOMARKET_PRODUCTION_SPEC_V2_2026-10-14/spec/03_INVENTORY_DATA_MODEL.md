# 03 — Строгая спецификация склада и резервов

## INV-DM-001. Термины и источник истины

В B2B хранить `skus.on_hand` (текущее фактическое количество, бывшее `stock`), `skus.reserved_quantity` (активные брони), `available=on_hand-reserved_quantity` (вычисляемое значение), `skus.price_minor`, `currency`. **Не** менять `on_hand` при `reserve`; при `unreserve` уменьшается только `reserved_quantity`; при `fulfill` уменьшаются оба `on_hand` и `reserved_quantity`. `stock` -> `on_hand` мигрировать expand/backfill/contract, не rename в один шаг при работающих клиентах. Если бизнес допускает отрицательные остатки/backorder — отдельная сущность и ADR, текущий релиз запрещает.

## INV-DM-002. Транзакционные таблицы

- `inventory_order_lifecycle`: `order_id UUID PK`, `fingerprint char(64)`, `state ENUM(NEW, RESERVED, CANCELLED, FULFILLED)`, `version BIGINT`, `reserved_at`, `terminal_at`, `source`, `created_at/updated_at`, `result JSONB`; терминальные записи не исчезают по short TTL.
- `reservation_lines`: `order_id`, `sku_id`, `quantity>0`, `state ACTIVE|RELEASED|FULFILLED`, unique `(order_id,sku_id)`; FK order_lifecycle, FK sku, timestamps. Исторические строки остаются для reconciliation.
- `inventory_ledger`: append-only `entry_id`, `event_id UNIQUE`, `order_id nullable`, `sku_id`, `delta_on_hand`, `delta_reserved`, `reason`, `actor_type/id`, `occurred_at`, `correlation_id`; изменения ledger и skus обязаны совершаться в одном commit.
- `inventory_request_keys`: `(caller,idem_key)` PK, `order_id`, `fingerprint`, `response/status`, TTL только для кэша HTTP ответа, никогда не для контроля order terminal lifecycle.
- `stock_adjustments`: adjustment_id, sku_id, delta, reason, seller_id, idempotency key; видимые продавцу изменения только через этот audit-able workflow.

## INV-DM-003. DB constraints и обновления

```
CHECK on_hand >= 0
CHECK reserved_quantity >= 0
CHECK reserved_quantity <= on_hand
CHECK price_minor >= 0
CHECK reservation_lines.quantity > 0
UNIQUE (order_id, sku_id) on reservation_lines
UNIQUE (sku_id, event_id) or UNIQUE(event_id) inventory_ledger
```

- Плюс `NOT NULL`, FK, допустимые статусы, объём/длина строк, индекс `(state, next_retry_at)` у jobs. Потребуются migration preflight и устранение существующих нарушений; constraint лучше добавить `NOT VALID` / `VALIDATE CONSTRAINT` по поддерживаемой схеме.
- Всегда блокировать `inventory_order_lifecycle` по `order_id`, затем `skus` **в отсортированном UUID порядке**, затем `reservation_lines`; глобальный lock order одинаков для reserve/cancel/fulfill/update, чтобы избежать deadlock. Для отсутствующей lifecycle записи сначала `INSERT .. ON CONFLICT DO NOTHING`, затем `SELECT .. FOR UPDATE`; конкурентные reserve и unreserve сериализуются на одном ключе, даже до появления строк reserve.
- SKU update должен блокировать строки SKU, проверять `new_on_hand >= reserved_quantity` и не менять reserved; если нет запаса -> `409 STOCK_BELOW_RESERVED` со safe details.
- `READ COMMITTED` + explicit row locks достаточен при доказанной сериализации на order id и sorted SKUs. При SQLSTATE 40001/40P01 bounded retry всей транзакции с jitter; не повторять произвольный side effect вне DB transaction.
- Любая ловимая аномалия -> rollback, error event, alert, без использования `max(quantity,0)` в качестве «исправления».

## INV-DM-004. Reserve: строгий алгоритм

1. Проверить service identity/scope, JSON Schema, тот же normalized fingerprint: отсортированные `sku_id`, без дублей/нулевых/отрицательных qty, количество товаров в пределах limits.
2. BEGIN; создать lifecycle row `order_id` при отсутствии, `FOR UPDATE`; если `CANCELLED/FULFILLED` -> 409 `ORDER_TERMINAL`, **никаких резервов**, если `RESERVED` и fingerprint равен -> ответ из сохранённого state, иначе 409 `IDEMPOTENCY_CONFLICT`.
3. `SELECT skus WHERE id IN ... ORDER BY id FOR UPDATE`; все SKU существуют/active/sellable/approved и имеют `available >= requested qty`. Price snapshot/B2C quote policy проверяется в документе order saga.
4. Atomic update `reserved+=qty`, вставить lines, ledger с `delta_reserved=+qty`, lifecycle state `RESERVED`, outbox события для B2C при необходимости; COMMIT.
5. Ответ `201` (новый), `200` (идемпотентный повтор); timeout after commit не означает отсутствие reserve.
6. При недостатке доступности **ни один SKU не резервируется**; rollback всей операции, 409 `INSUFFICIENT_STOCK` с sku_id and available (если разрешено скрывать внешним клиентам, B2C переводит в понятную ошибку).

## INV-DM-005. Unreserve: tombstone раньше/после reserve

1. BEGIN; создать lifecycle row для `order_id` при отсутствии (state `NEW`); заблокировать `FOR UPDATE`.
2. `NEW` -> записать **terminal** `CANCELLED` (tombstone), `delta=0`, COMMIT `200 CANCELLED`. Это навсегда предотвращает «опоздавший reserve».
3. `RESERVED` -> lock SKU sorted, verify line quantities, уменьшить reserved exactly, перевести lines `RELEASED`, lifecycle `CANCELLED`, append ledger, COMMIT. Повтор -> прежний результат.
4. `CANCELLED` -> `200` с сохранённым outcome (при совпадающем semantic scope); `FULFILLED` -> `409 ALREADY_FULFILLED` (отмена после отправки/доставки ведёт в отдельный returns workflow, не увеличивать склад произвольно).
5. Неправильные списки items из external request не влияют на lines: источник истины — B2B линии по order_id. При любом несовпадении fingerprint — `409 IDEMPOTENCY_CONFLICT`.

## INV-DM-006. Fulfill

`NEW` -> 409 `NOT_RESERVED`; `CANCELLED` -> 409; `FULFILLED` -> прежний `200`. Для `RESERVED`: order row lock, sorted SKU locks; проверка всех lines/stock; `on_hand-=qty`, `reserved-=qty`, lines `FULFILLED`, lifecycle `FULFILLED`, ledger per SKU, outbox ack, COMMIT; любое нарушение abort transaction и critical alert. Не допускать partial fulfill для v1; если понадобится частичная поставка, вводить `shipment_id` и отдельный ledger/idempotency contract.

## INV-DM-007. Reconciliation и очистка

- Каждые 5 мин B2B SQL-проверка `reserved_quantity` vs sum of ACTIVE lines, nonnegative/check constraints, orphan lifecycle/reservation/ledger; любые отличия -> P0 incident + stop writes affected SKU, безопасная повторная проверка, ручной approved repair via ledger.
- Каждые 5 мин cross-service reconcile: B2C orders statuses vs B2B lifecycle (через signed paginated admin endpoint/инкрементальные агрегаты). `CREATED/RESERVED`, `CANCEL_PENDING/CANCELLED`, `DELIVERY_FINALIZING/FULFILLED` разбирать по матрице, непонятные состояния -> queue, не silent auto-delete.
- Garbage collection только после запрета replay через retained lifecycle tombstone (business retention >= life of order/retention policy). Нельзя удалять идемпотентность бизнес-транзакций из-за часового TTL.

## INV-DM-008. Обязательные конкурентные тесты

100 параллельных reserve одной SKU; reserve vs stock decrease; reserve slow vs unreserve first; retry after 1/24/720 часов; concurrent fulfill+unreserve; 3 SKU с разным порядком в запросах; deadlock injected; kill after each BEGIN/lock/ledger/commit/response; crash worker and retry; 1k random sequences (property-based state machine). Для каждого: сумма активных линий=reserved, никогда минус, terminal lifecycle не воскресает, exactly one fulfillment effect. См. `qa/ACCEPTANCE_TEST_PLAN.md`.
