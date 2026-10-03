# Internal API compatibility

Audited against Protocols `3b405c6844f26d2d7c4ea32a44ea2f419723e8d0` and `AUDITED_CODE_SHA` `5aa94c9f6f39e82fb36878c80df18453d3d3be6a`.

| Sender | Method / URL | Header | Payload | Receiver | Result |
|---|---|---|---|---|---|
| Admin Moderation client | POST `/api/v1/moderation/events` | `X-Service-Key` | current `ModerationEventRequest` | B2B moderation router | PASS: 204 |
| B2B moderation reason resolver | GET `/api/v1/blocking-reasons` | `X-Service-Key` | `reason_id` selected from canonical response | Moderation source of truth | PASS: real title/comment snapshot; missing/unavailable reason is rejected |
| B2C cart enrichment | POST `/api/v1/public/products/batch` + GET `/api/v1/products/{product_id}` for omitted records | `X-Service-Key` | batch `{product_ids}` only; service detail fallback preserves unavailable status | B2B catalog routers | PASS: canonical schema; no `include_unavailable` |
| B2C checkout | POST `/api/v1/inventory/reserve` | `X-Service-Key` | `ReserveRequest`; the same key is bound to its canonical request hash | B2B inventory router | PASS: 200 exact replay / 409 contract errors |
| B2C cancellation/retry | POST `/api/v1/inventory/unreserve` | `X-Service-Key` | `InventoryOrderRequest` | B2B inventory router | PASS: 200 |
| B2B outbox | POST `/api/v1/b2b/events` | `X-Service-Key` | `B2BEvent` | B2C B2B-events router | PASS: 202; duplicate is 409 |

The B2B outbox persists the event in the inventory/moderation transaction and retries failed delivery. Cancellation intent is committed on the order as `CANCEL_PENDING` before B2B unreserve and is retried by the B2C worker after restart. Checkout commits a request-fingerprinted pre-reserve intent before B2B reserve; if local persistence does not commit, the worker retries the exact unreserve payload, but first deletes stale intent without unreserving when the Order did commit. A completed compensation remains as an operation tombstone, preventing B2B's cached reserve replay from producing an order after the reservation was released. B2C computes cart availability from fresh B2B product data, avoiding stale event-derived availability after a re-stock or re-moderation.
