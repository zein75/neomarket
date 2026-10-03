# NeoMarket pre-submission contract matrix

Sources frozen for this audit:

- Canon: `2ff93a4cebc119e860385b318ebd8753fda1d801`
- Protocols: `3b405c6844f26d2d7c4ea32a44ea2f419723e8d0` (`master`)
- AUDITED_CODE_SHA: `5aa94c9f6f39e82fb36878c80df18453d3d3be6a` (durable checkout/cancellation remediation, compensated-operation tombstone, shared checkout/worker operation lock, and rollback-safe compensation payload)

| Task | Endpoint | Method | Auth/Header | Request | Success | Errors | OpenAPI | Canon |
|---|---|---|---|---|---|---|---|---|
| Reserve | `/api/v1/inventory/reserve` | POST | `X-Service-Key` | `ReserveRequest`: UUID key, order, items | 200 exact stored `ReserveResponse` including `reserved_at` | 409 root `Error`, failed SKUs at `details.failed_items`; same key/different request → conflict | b2b | reserve-sku |
| Unreserve | `/api/v1/inventory/unreserve` | POST | `X-Service-Key` | `InventoryOrderRequest`: order and items | 200 `InventoryOrderResponse` including `processed_at` | root `Error` | b2b | reserve-sku |
| Moderation | `/api/v1/moderation/events` | POST | `X-Service-Key` | typed `ModerationEventRequest` (`event_type`, required `blocking_reason_id` for BLOCKED, typed reports) | 204 empty | 400/401 root `Error` | b2b | apply-moderation |
| Catalog batch | `/api/v1/public/products/batch` | POST | `X-Service-Key` | `{product_ids}` only | 200 public product array; omitted products are enriched via service detail | 401/422 | b2b | b2c-8-cart |
| Cart read | `/api/v1/cart` | GET | JWT or `X-Session-Id` | — | 200 `CartResponse` | root `Error` | b2c | b2c-8-cart |
| Cart items | `/api/v1/cart/items`, `/api/v1/cart/items/{sku_id}` | POST/PATCH/DELETE | JWT or `X-Session-Id` | add/update models; path is SKU UUID | POST/PATCH 200 `CartResponse`; DELETE 204 empty | root `Error` | b2c | b2c-8-cart |
| Clear cart | `/api/v1/cart` | DELETE | JWT or `X-Session-Id` | — | 204 empty | root `Error` | b2c | b2c-8-cart |
| Validate/merge | `/api/v1/cart/validate`, `/api/v1/cart/merge` | POST | JWT or session; merge needs session | — | 200 validation/cart | root `Error` | b2c | b2c-8-cart |
| Checkout | `/api/v1/orders` | POST | JWT + `Idempotency-Key` | `OrderCreateRequest` | 201 created / 200 exact idempotent replay `OrderResponse` | 400/401/409/422/503 root schema | b2c | b2c-9-checkout: durable pre-reserve intent; committed order is saga confirmation; compensated ambiguous operations cannot be replayed into orders |
| Cancel | `/api/v1/orders/{order_id}/cancel` | POST | JWT | optional cancellation reason | 200 `OrderResponse` | 401/404/409 root `Error` | b2c | b2c-11-cancel-order: commit `CANCEL_PENDING` before unreserve; retry after final-commit failure |

## Resolved source conflicts

- Historical cart review expected a response body; current Protocols master requires `204 No Content`. The canonical implementation follows Protocols master.
- A prior local report incorrectly called replay `201`; Protocols master declares 201 for creation and 200 for the same-key replay. The implementation now follows both success statuses.
- Older moderation flow used `status` and a whole `blocking_reason`; current wire contract requires `event_type` and `blocking_reason_id`. The canonical endpoint accepts only the current request shape. The old route is an undocumented compatibility alias.
- The cancellation DoD text once said ASSEMBLING was forbidden, whereas current Protocols and the latest arbiter feedback allow CREATED, PAID, ASSEMBLING and DELIVERING. The implementation follows the current contract.
- Canon's legacy B2B→B2C prose mentions `/api/v1/events/product`, while Protocols master declares `/api/v1/b2b/events`; the sender follows the OpenAPI wire contract and the old route is not canonical.
