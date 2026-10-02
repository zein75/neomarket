# Internal API compatibility

Audited against Protocols `3b405c6844f26d2d7c4ea32a44ea2f419723e8d0`.

| Sender | Method / URL | Header | Payload | Receiver | Result |
|---|---|---|---|---|---|
| Admin Moderation client | POST `/api/v1/moderation/events` | `X-Service-Key` | current `ModerationEventRequest` | B2B moderation router | PASS: 204 |
| B2C checkout | POST `/api/v1/inventory/reserve` | `X-Service-Key` | `ReserveRequest`; the same key is bound to its canonical request hash | B2B inventory router | PASS: 200 exact replay / 409 contract errors |
| B2C cancellation/retry | POST `/api/v1/inventory/unreserve` | `X-Service-Key` | `InventoryOrderRequest` | B2B inventory router | PASS: 200 |
| B2B outbox | POST `/api/v1/b2b/events` | `X-Service-Key` | `B2BEvent` | B2C B2B-events router | PASS: 202; duplicate is 409 |

The B2B outbox persists the event in the inventory/moderation transaction and retries failed delivery. Cancellation intent is stored on the order and retried by the B2C worker after restart. If checkout reserves successfully but local persistence and immediate unreserve both fail, `pending_reservation_compensations` persists the exact unreserve payload and the same worker retries it after restart. B2C computes cart availability from fresh B2B product data, avoiding stale event-derived availability after a re-stock or re-moderation.
