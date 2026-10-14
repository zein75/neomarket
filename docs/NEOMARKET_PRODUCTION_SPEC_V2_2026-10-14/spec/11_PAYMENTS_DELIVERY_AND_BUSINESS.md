# 11 — Product completeness: payments, shipping, refunds, seller settlements, compliance

## BUS-001. Неочевидный пробел текущего состояния

Обнаруженный аудит не подтвердил реального платежного провайдера, доставки с доказательством исполнения, фискализации, возврата платежей, расчётов с продавцами, customer support и legal data policies. `PAID`/`DELIVERED` enum в коде **не доказывает**, что деньги получены/товар доставлен. Для «полного production marketplace» бизнес обязан утвердить, какие из перечисленных сценариев входят в go-live; обещать их без реализации и верификации нельзя.

## BUS-002. Gate запуска по денежным операциям

**Вариант А (ограниченный запуск):** продажи без online card capture (например, offline invoice/COD там, где это законно и допустимо по продуктовым требованиям) — online pay controls скрыты/feature-flag disabled, `payment_status=NOT_REQUIRED` или `PENDING_OFFLINE`, действия `mark_paid` доступны только уполномоченному финансовому оператору с доказательством оплаты, audit и dual control на значимые суммы. Платформа не обещает платежи через неработающий интерфейс. Это не полный production онлайн-платежей.

**Вариант B (полный online marketplace):** отдельный PSP integration проект с approved provider, contractual/legal compliance и тестами ниже. Решение утверждается владельцем до full GO. Ни один статус PAID не меняется при callback browser/user input.

## BUS-003. PSP интеграция — обязательные контракты при Варианте B

- `payment_attempts`: payment_id, order_id, provider, external_payment_id unique, idempotency_key, amount_minor, currency, state (`CREATED/AUTHORIZED/CAPTURED/FAILED/REFUNDED/...`), authenticated webhook event ids, timestamps and reconciliation state. Не хранить PAN/CVV; использовать hosted checkout/provider tokens, PCI scope минимизировать.
- Authorization/capture/refund server-to-provider with idempotency, signed webhooks with timestamp skew/replay controls, IP alone insufficient; verified signature, event uniqueness and amount/currency/order matching. Provider webhook is *at least once*, persisted inbox. Browser redirect => pending, not paid.
- Inventory reserve before payment decision according to exact business policy; on payment failure/expiry trigger cancellation saga; if payment captured but stock reserve no longer valid, **не** скрывать случай: refund/review as durable job. Capture/refund exactly-once business effect under provider keys, daily provider reconciliation, settlement/disputes operations, incident runbooks.
- Client flow must state expiration, authorization/capture window and late webhook behavior. Business owner approves when cancellation is forbidden, when refund is automatic/manual, and seller payout timing. Cross currency/tax/commissions handled via financial ledger, not mutable order_total alone.

## BUS-004. Delivery/logistics

- Logistics owner chooses: in-house operator, carrier integration, or manual controlled workflow. Tracking events authenticated, delivery proof immutable (carrier reference, signature/hash, timestamp), transition delivery_confirmed -> durable inventory fulfill as in `spec/04`.
- Lost parcel/refund/partial delivery/returns demand separate state machine; for v1 without partial delivery, block unsupported partial shipment, instruct operator to use supported process and display accurate status. Tests with duplicate/out-of-order carrier webhooks, cancellation race and return after fulfill.

## BUS-005. Seller finance, privacy and legal readiness

- If sellers receive transfers, create seller balances/commissions/payout ledger with double-entry or auditable immutable transactions, PSP reconciliation and least-privilege authorizations. Нельзя отправлять выплаты как необратимый HTTP side-effect до durable accounting transaction.
- Tax/VAT/receipts/consumer rights/returns, handling of PII, age-related consumer rights, account deletion, retention and regulator incident notification depend on operating country and business model and require written legal approval. Это не гарантируется техническими тестами.
- Terms of service, privacy notice, cookie policy (if applicable), seller agreement, returns policy, user support and complaint SLA must be approved and shown to customers before taking real orders.

## BUS-006. Acceptance

For Option A: verify no accessible online payment endpoint, fake user `PAID` attempts 403, operator audit proof and offline reconciliation. For Option B: PSP sandbox signature validation, duplicate webhook, capture-response-loss, refund-response-loss, amount mismatch, replay webhook, delayed payment after cancelled reserve, provider outage, chargeback workflow, provider reconciliation and financial double entry; legal/PSP sign-off. For delivery: authenticated proof, duplicate webhook harmless, post-delivery stock decremented once; no silent success.
