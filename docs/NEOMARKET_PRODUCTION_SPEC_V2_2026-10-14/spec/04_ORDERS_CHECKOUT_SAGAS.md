# 04 — Заказы, checkout, отмена, доставка, платежные статусы

## ORD-001. Ownership и статусы

B2C — единственный источник истины для покупателей, заказов и истории; B2B — для броней, физического остатка и fulfillment. В `orders` сохранить immutable snapshots SKU, названия, quantity, `unit_price_minor`, currency, address, delivery method, tax/shipping (когда применимо), total and created_at; изменения товара не переписывают историю заказа. `orders.version` для CAS optimistic concurrency. Платёжный статус не смешивается со статусом логистики.

**Состояние checkout_intent:** `NEW → RESERVING → RESERVED → COMMITTED` либо `RESERVING/RESERVED → COMPENSATING → COMPENSATED`; неопределённые результаты — `RECONCILE_REQUIRED`, окончательный отказ `FAILED_FINAL` после проверки отсутствия активной брони. Intent содержит `order_id`, `(buyer_id,idempotency_key) UNIQUE`, normalized fingerprint, immutable items, `lease_owner`, `lease_until`, monotonically increasing fencing_token, retry_count, next_retry_at, status. Один B2C owner на intent.

**Заказ:** `CREATED → CONFIRMED → ASSEMBLING → DELIVERING → DELIVERY_FINALIZING → DELIVERED` или (если отмена допустима до delivery) `CREATED|CONFIRMED|ASSEMBLING → CANCEL_PENDING → CANCELLED`. `DELIVERING` отменяется только по утверждённым правилам возвратов; нельзя молча снимать бронь после физической передачи. `CANCELLED` и `DELIVERED` терминальны; post-delivery return — отдельный workflow.

**Оплата:** отдельно `NOT_REQUIRED | PENDING | AUTHORIZED | CAPTURED | FAILED | REFUND_PENDING | REFUNDED`. Из frontend нельзя напрямую выставить CAPTURED/PAID; online PSP обязателен, если заявлены платежи.

## ORD-002. Checkout: идемпотентный commit and unknown outcomes

1. Подтвердить JWT, owner корзины/адреса, все quantities>0, ограничения суммы/списка SKU, seller and publication. **Не доверять** переданной клиентом цене: snapshot корзины строится сервером и подтверждается покупателем.
2. Client `POST /api/v1/orders`, `Idempotency-Key` UUID. Canonical hash B2C из user_id, нормализованных items, address version, delivery method, currency. Unique per-user request key. Тот же key+hash возвращает прежний result, тот же key+другой hash -> 409.
3. BEFORE downstream HTTP: `BEGIN` B2C, записать durable checkout_intent with immutable proposed order_id, `COMMIT`. Если создание intent не удалось, никаких резервов. Worker or request leases intent with SELECT FOR UPDATE SKIP LOCKED+fencing.
4. B2B `reserve(order_id,items,request_fingerprint)` is protected, terminal-marker aware and idempotent. Семантический B2B fingerprint отдельный: canonical hash только `order_id + normalized sku_id/qty`, B2B **пересчитывает его**, не доверяет произвольной строке из HTTP. B2C request fingerprint/quote включает более широкие client fields.
5. B2B returns durable `RESERVED` plus authoritative price snapshot in `items[]`: sku_id,product_id, quantity,unit_price_minor,currency,product_revision. B2C сравнивает с **последней серверной ценой показанной покупателю**; при изменении вызывает durable `COMPENSATING -> unreserve` того же order_id. До terminal ack -> 202 PENDING; после terminal ack клиент получает `409 PRICE_CHANGED` с приглашением подтвердить новую цену.
6. При совпадении prices и valid lease/fencing B2C в одной транзакции INSERT order/items/history, intent `COMMITTED`, outbox notifications, commit. Только после durable commit возвращать 201. Idem replay returns 200.
7. B2B reserve response timeout/connection reset => **UNKNOWN**, не трактовать как неуспех. Повтор с тем же order_id и semantic hash; если операция уже идёт, возвращать `202 PENDING` только при committed intent и stable operation poll URL, не создавать второй заказ.
8. Если процесс умер after B2B commit, before B2C commit, worker выясняет через exact order_id и либо безопасно завершает order, либо сперва фиксирует `COMPENSATING` затем вызывает B2B `unreserve`/terminal tombstone. После перехода в COMPENSATING поздний worker/HTTP request **не может** создать Order.

**Инвариант:** для каждой успешной 201/200 операции есть единственный B2C order и один B2B RESERVED lifecycle с идентичным SKU snapshot; если не удалось, возможен только честный pending или terminal compensated. Ни orphan reserves, ни утверждений success при неизвестном outcome.

## ORD-003. Cancellation

- Buyer (owner) or audited operator: `POST /orders/{id}/cancel`; compare-and-set status -> `CANCEL_PENDING`, persist `cancel_job`/outbox and history **в одной B2C транзакции**, return 202 if pending.
- Worker with durable lease calls protected B2B `unreserve(order_id)`. B2B `CANCELLED` -> B2C final `CANCELLED`, `FULFILLED` -> 409 and supervised returns/dispute, unknown -> retry same ID+backoff, no premature CANCELLED.
- Concurrent cancel and fulfill serializable per order (B2C version and B2B lifecycle row lock); stale command safe and idempotent. Optional requested reason bounded and sanitized.
- Failure before/after B2B unreserve commit or client response reconstructed by replay. No direct DELETE reservation endpoint.

## ORD-004. Delivery and fulfillment

- Only authenticated and audited fulfillment operator/carrier principal can confirm delivery; proof/correlation/timestamp, scope `delivery.confirm`. Browser user cannot set DELIVERED. Confirm changes B2C `DELIVERING→DELIVERY_FINALIZING`, adds durable pending fulfillment with retry state.
- Dedicated fulfillment worker calls B2B `fulfill` exactly one business effect. B2B state `FULFILLED` -> B2C `DELIVERED`, save history/ack. On outage order remains `DELIVERY_FINALIZING`, with backlog alert; never claim DELIVERED on unacknowledged external change.
- Retry/delayed response and duplicate delivery webhook cannot decrement `on_hand` twice. Unsupported partial fulfill forbidden until shipment_id/item-level ledger and separate ADR are built. Delivered returns are an independent compensated flow, not unreserve.

## ORD-005. Error contract & state graph acceptance

| Failure point | Recovery invariant |
|---|---|
| Before checkout intent commit | no B2B reserve and no order |
| After intent commit, before reserve | worker resumes same order_id |
| After reserve commit, response lost | B2B idem replay, no extra hold |
| After reserve, before order commit | intent worker either completes or cancels, never both |
| Unreserve wins before old reserve | B2B tombstone prevents late reserve |
| Cancel after fulfill | explicit conflict/returns case, no stock resurrection |
| Fulfill completed, HTTP ACK lost | repeat -> same result, order eventually DELIVERED |
| 2+ B2C workers | lease/fencing prevents concurrent decisions, repeats remain safe |
| DB restored at different times | freeze unsafe writes, reconcile, replay same IDs |

409: wrong state/price changed/insufficient stock/semantic conflict; 503: unavailable before any durable operation; 202: operation saved and pollable, not completed. Error payload `error.code/message/details/retryable`, request_id. Status histories append-only, API only returns order owner data.

## ORD-006. Testing

ORD-T01..T18, INV-T03..T08, DR-T03 and SEC-T03 tests from `qa/ACCEPTANCE_TEST_PLAN.md`: parallel checkout, lost reply, crash around every commit, cancel vs delivery, duplicate webhook, price change, timeout, 202 polling, same and altered idempotency keys, client owner/access checks. Real PostgreSQL/2+ workers, randomized seeds, no fake repository as exclusive evidence.
