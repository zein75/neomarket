# NeoMarket pre-submission contract matrix

Sources frozen for this audit:

- Canon: `2ff93a4cebc119e860385b318ebd8753fda1d801`
- Protocols: `3b405c6844f26d2d7c4ea32a44ea2f419723e8d0` (`master`)
- Project baseline: `7ce62cb9cbe7e0d130bbf39df3d42578a7927dfc`

| Task | Endpoint | Method | Auth/Header | Request | Success | Errors | OpenAPI | Canon |
|---|---|---|---|---|---|---|---|---|
| Reserve | `/api/v1/inventory/reserve` | POST | `X-Service-Key` | `ReserveRequest`: UUID key, order, items | 200 `ReserveResponse` including `reserved_at` | 409 root `Error` | b2b | reserve-sku |
| Unreserve | `/api/v1/inventory/unreserve` | POST | `X-Service-Key` | `InventoryOrderRequest`: order and items | 200 `InventoryOrderResponse` including `processed_at` | root `Error` | b2b | reserve-sku |
| Moderation | `/api/v1/moderation/events` | POST | `X-Service-Key` | typed `ModerationEventRequest` (`event_type`, `blocking_reason_id`, typed reports) | 204 empty | 400/401 root `Error` | b2b | apply-moderation |
| Cart read | `/api/v1/cart` | GET | JWT or `X-Session-Id` | — | 200 `CartResponse` | root `Error` | b2c | b2c-8-cart |
| Cart items | `/api/v1/cart/items`, `/api/v1/cart/items/{sku_id}` | POST/PATCH/DELETE | JWT or `X-Session-Id` | add/update models; path is SKU UUID | 200 `CartResponse` | root `Error` | b2c | b2c-8-cart |
| Clear cart | `/api/v1/cart` | DELETE | JWT or `X-Session-Id` | — | 204 empty | root `Error` | b2c | b2c-8-cart |
| Validate/merge | `/api/v1/cart/validate`, `/api/v1/cart/merge` | POST | JWT or session; merge needs session | — | 200 validation/cart | root `Error` | b2c | b2c-8-cart |
| Checkout | `/api/v1/orders` | POST | JWT + `Idempotency-Key` | `OrderCreateRequest` | 201 `OrderResponse` | 400/401/409/422/503 root schema | b2c | b2c-9-checkout |
| Cancel | `/api/v1/orders/{order_id}/cancel` | POST | JWT | optional cancellation reason | 200 `OrderResponse` | 401/404/409 root `Error` | b2c | b2c-11-cancel-order |

## Resolved source conflicts

- Historical cart review expected DELETE item `204`; current Protocols master requires `200 CartResponse`. The canonical implementation follows Protocols master.
- Historical checkout replay used `200`; current Protocols master declares `201` as its sole success response while retaining replay semantics. Replays return the original order with `201` and do not create or reserve again.
- Older moderation flow used `status` and a whole `blocking_reason`; current wire contract requires `event_type` and `blocking_reason_id`. The canonical endpoint accepts only the current request shape. The old route is an undocumented compatibility alias.
- The cancellation DoD text once said ASSEMBLING was forbidden, whereas current Protocols and the latest arbiter feedback allow CREATED, PAID, ASSEMBLING and DELIVERING. The implementation follows the current contract.
