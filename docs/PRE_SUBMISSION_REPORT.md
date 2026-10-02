# NeoMarket pre-submission audit

## Sources

Project baseline SHA: `7ce62cb9cbe7e0d130bbf39df3d42578a7927dfc`  
Canon SHA: `2ff93a4cebc119e860385b318ebd8753fda1d801`  
Protocols SHA: `3b405c6844f26d2d7c4ea32a44ea2f419723e8d0`

## Result

Critical: 0  
High: 0  
Medium: 0  
Low: 0

The only unverified gate is the required real-PostgreSQL concurrency run: Docker Desktop was unavailable in this audit environment. This is an environment limitation, not a suppressed test result.

## Task 1 — Reserve / Unreserve

- Canonical inventory routes, typed reserve/unreserve requests, response timestamps and root-level errors are covered.
- Multi-SKU reserve, replay preserving the original response, parent moderation status, transactional outbox and retry regressions are in the B2B suite.
- Historical arbiter blockers: `[x]` response timestamps, `[x]` error envelope, `[x]` multi-SKU idempotency scope, `[x]` persisted outbox, `[x]` retry.

## Task 2 — Moderation

- Canonical route is `/api/v1/moderation/events`; the historical route is hidden from the generated schema.
- Current `event_type` request model and typed field reports are enforced; Admin emits that exact shape.
- Blocking creates a durable B2C outbox event; hard blocks emit `PRODUCT_HARD_BLOCKED`.

## Task 3 — Cart

- SKU-addressed mutation, clear, validate, explicit merge and login merge are covered.
- DELETE item now returns the contract-required 200 `CartResponse` (not historical 204).
- Price change and distinct unavailable cases are covered; no reservation occurs while adding to cart.

## Task 4 — Checkout

- Checkout validates address ownership and cart, snapshots address/prices, uses canonical B2B reserve, scopes idempotency by buyer and compensates a failed local write.
- All Order response relationships are eagerly loaded before serialization.
- Replays return the original order as protocol status 201 without a second reserve.

## Task 5 — Cancel

- CREATED, PAID, ASSEMBLING and DELIVERING are cancellable; terminal statuses return contract error.
- Ownership uses 404, cancellation locks the row, sends typed unreserve payload, persists CANCEL_PENDING and retries durably.
- Response relationships are loaded before serialization.

## Internal integration matrix

Moderation -> B2B: PASS  
B2B -> B2C: PASS  
B2C -> B2B reserve: PASS  
B2C -> B2B unreserve: PASS

See [INTERNAL_API_COMPATIBILITY.md](INTERNAL_API_COMPATIBILITY.md) for method/header/payload mapping.

## Tests

| Suite | Result |
|---|---:|
| B2B unit/regression | 129 passed |
| B2C unit/regression | 103 passed |
| Admin unit/regression | 16 passed |
| PostgreSQL concurrency | not run — Docker Desktop engine unavailable |

## OpenAPI contract check

Generated application schemas were checked for the changed canonical paths:

- B2B moderation: POST `/api/v1/moderation/events` -> 204; old route excluded.
- B2C cart item DELETE: 200 `CartResponse`.
- B2C checkout: 201 `OrderResponse`.
- B2C B2B-event receiver: 202.

## Remaining risks

No code-level critical or high finding remains. Before submission, run the PostgreSQL gate below after Docker Desktop is started; do not claim that its concurrency semantics were executed until then.

## Reproduction

```powershell
cd services/b2b; uv run pytest tests/ -q
cd ../b2c; uv run pytest tests/ -q
cd ../admin; uv run pytest tests/ -q
cd ../..; docker compose up -d postgres
```
