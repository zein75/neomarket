# NeoMarket final pre-submission audit

## Sources

Audited application SHA: `7459d466f53d26f9865998a1558b8440c2c6020b`
Canon SHA: `2ff93a4cebc119e860385b318ebd8753fda1d801`  
Protocols SHA: `3b405c6844f26d2d7c4ea32a44ea2f419723e8d0`

## Result

Critical: 0  
High: 0  
Medium: 0  
Low: 0

The real PostgreSQL migration and behavioural concurrency gates passed on Docker PostgreSQL 16. Checkout now persists a pre-reserve intent and commits the Order inside the saga; cancellation commits `CANCEL_PENDING` before unreserve. Checkout finalization and the compensation worker share an operation-level PostgreSQL advisory lock keyed by the deterministic checkout order id. Compensation additionally persists `PENDING → COMPENSATING → COMPENSATED`: the pre-unreserve `COMPENSATING` commit blocks a delayed checkout even if the process dies after B2B unreserve succeeds and before the final tombstone commit.

## Task 1 — Reserve / Unreserve

- Canonical inventory routes, typed reserve/unreserve requests, response timestamps and root-level errors are covered.
- Multi-SKU reserve, exact replay preserving the original response, same-key/different-payload rejection, parent moderation status, transactional outbox and retry regressions are in the B2B suite.
- Historical arbiter blockers: `[x]` response timestamps, `[x]` `Error.details.failed_items` envelope, `[x]` multi-SKU idempotency scope, `[x]` request fingerprint, `[x]` persisted outbox, `[x]` retry.

## Task 2 — Moderation

- Canonical route is `/api/v1/moderation/events`; the historical route is hidden from the generated schema. The B2B→B2C receiver is the frozen `/api/v1/b2b/events`; its older product-event adapter is hidden from the generated schema.
- Current `event_type` request model, required `blocking_reason_id` for BLOCKED, and typed field reports are enforced; Admin emits only canonical fields, while B2B resolves the real seller-facing title/comment from the moderation reason source of truth.
- Blocking creates a durable B2C outbox event; both soft `BLOCKED` and internal terminal `HARD_BLOCKED` emit canonical `PRODUCT_BLOCKED`.

## Task 3 — Cart

- SKU-addressed mutation, clear, validate, explicit merge and login merge are covered.
- DELETE item returns the contract-required 204 empty response.
- Price change and distinct unavailable cases are covered; no reservation occurs while adding to cart.

## Task 4 — Checkout

- Checkout validates address ownership and cart, snapshots address/prices, uses canonical B2B reserve, scopes idempotency by buyer and commits a durable intent before reserve. A committed order deletes the intent; recovery checks for that order before any unreserve, while an orphaned reservation is compensated durably. Successful compensation retains a tombstone and late reuse of that key returns 409 rather than an order without a reservation. The pre-unreserve state is durable, so a crash or lost unreserve response cannot turn B2B's cached reserve replay into an Order without a live reservation.
- All Order response relationships are eagerly loaded before serialization.
- Replays return the original order as protocol status 200 without a second reserve.

## Task 5 — Cancel

- CREATED, PAID, ASSEMBLING and DELIVERING are cancellable; terminal statuses return contract error.
- Ownership uses 404, cancellation locks the row, sends typed unreserve payload, commits CANCEL_PENDING before B2B unreserve and retries durably if either unreserve or the final CANCELLED commit fails.
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
| B2B unit/regression | 134 passed; 3 PostgreSQL-gated cases run separately inside Docker |
| B2C unit/regression | 121 passed; 4 PostgreSQL-gated cases run separately inside Docker |
| Admin unit/regression | 16 passed |
| PostgreSQL B2B migrations | PASS: head `0017_reserve_request_hash` |
| PostgreSQL B2C migrations | PASS: clean and 0021→head upgrades reach `0022_compensation_state`; existing tombstone/pending rows backfill to `COMPENSATED`/`PENDING` |
| PostgreSQL B2B behavioural concurrency | PASS: 3 passed |
| PostgreSQL B2C behavioural concurrency | PASS: 4 passed, including retry-vs-compensation serialization and durable `COMPENSATING` visibility from independent AsyncSession connections |
| Docker runtime E2E | PASS: healthy Admin/B2B/B2C/PostgreSQL/Redis stack; cart → checkout → replay → cancel → clear; soft/hard moderation cascades; seller hard-block 403; durable outbox and CANCEL_PENDING recovery after dependent-service restart. |

## OpenAPI contract check

Generated application schemas were checked for the changed canonical paths:

- B2B moderation: POST `/api/v1/moderation/events` -> 204; old route excluded.
- B2C cart item DELETE: 204 empty response.
- B2C checkout: 201 `OrderResponse` for creation; 200 `OrderResponse` for idempotent replay.
- B2C B2B-event receiver: 202.

## Remaining risks

No code-level critical or high finding remains. PostgreSQL migrations and dedicated behavioural concurrency tests were executed inside Docker PostgreSQL 16 without skips. The older Windows-host test command may be slow because Docker Desktop connection setup exceeds the host watchdog; the container command below is the authoritative reproducible gate.

## Final freeze verification

- Runtime-tested application SHA: `7459d466f53d26f9865998a1558b8440c2c6020b` (the final production commit containing migration `0022_compensation_state`).
- Docker PostgreSQL migration gates: clean upgrade and `0021_compensation_tombstone` → head both passed, reaching `0022_compensation_state`; explicit legacy-row backfill was verified.
- Runtime commerce HTTP proof on the Docker stack: cart add/read → checkout `201` → same-key replay `200` → cancel `CANCELLED` → B2B reservation count `0` → cart clear `204` with an empty body.
- GitHub Actions must be read from the runs for the audited SHA above; runs for the preceding code SHA are deliberately not treated as evidence for this commit.
- Final local suites actually run on the audited code: B2B `134 passed, 3 host-gated PostgreSQL cases`; B2C `121 passed, 4 host-gated PostgreSQL cases`; Admin `16 passed`. All seven critical PostgreSQL cases ran inside Docker with no skips: B2B `3 passed`; B2C `4 passed`.

## Reproduction

```powershell
cd services/b2b; uv run pytest tests/ -q
cd ../b2c; uv run pytest tests/ -q
cd ../admin; uv run pytest tests/ -q
cd ../..; docker compose up -d postgres
docker compose exec -T -e NEOMARKET_POSTGRES_TEST_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/b2b b2c sh -lc "cd /app/services/b2c && uv run --group dev pytest tests/test_postgres_order_concurrency.py -q -rs"
docker compose exec -T -e NEOMARKET_POSTGRES_TEST_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/b2b b2b sh -lc "cd /app/services/b2b && uv run --group dev pytest tests/test_inventory_reservations.py -k 'postgres_' -q -rs"
```
