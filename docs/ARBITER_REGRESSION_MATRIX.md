# Arbiter regression matrix

Checked against project commit `b26cee243031266c4e7ad300afe6a5d785518214` and authoritative canon/protocols SHAs recorded in the pre-submission report.

| Task | Historical arbiter issue | Code fix | Regression test | Test type | Result |
|---|---|---|---|---|---|
| Reserve | replay recalculated inventory | persisted response + request hash | `test_postgres_same_key_different_payload_returns_conflict` | PostgreSQL | PASS |
| Reserve | multi-SKU idempotency collision | operation scoped by request hash | `test_postgres_multi_sku_reserve_and_replay` | PostgreSQL | PASS |
| Reserve | incorrect insufficient-stock envelope | root Error with `details.failed_items` | reserve 409 regression tests | unit | PASS |
| Moderation | BLOCKED without reason accepted | conditional Pydantic validation | `test_blocked_without_reason_is_rejected_by_contract_validator` | HTTP | PASS |
| Moderation | hard-block leaked as a different B2C event | both internal states emit `PRODUCT_BLOCKED` | `test_blocked_hard_sets_terminal_status`, `test_soft_block_emits_product_blocked` | unit | PASS |
| Moderation | unknown product used undeclared 404 | canonical endpoint returns declared 400 | `test_unknown_product_returns_declared_bad_request` | HTTP | PASS |
| Moderation | duplicate event repeated side effects | processed-event idempotency | duplicate-event tests in `test_apply_moderation.py` | unit | PASS |
| Cart | wrong DELETE addressing/response | SKU path and 204 empty body | `test_delete_item_contract` | HTTP | PASS |
| Cart | undeclared `include_unavailable` batch field | canonical `product_ids` request plus service-detail fallback | `test_b2b_batch_request_matches_canonical_schema_and_enriches_hidden_product` | contract | PASS |
| Cart | price/unavailable reason regressions | current enrichment and validation | cart price/reason tests | unit | PASS |
| Checkout | cross-user idempotency leak | ownership-scoped lookup | checkout ownership test | unit | PASS |
| Checkout | concurrent same-key IntegrityError | PostgreSQL idempotent replay | PostgreSQL checkout concurrency suite | PostgreSQL | PASS |
| Checkout | reserve succeeded but local write failed | durable compensation row/retry | compensation fault-injection tests | integration | PASS |
| Cancel | stale cancellation status list | current cancelable status set | cancel status regression tests | unit | PASS |
| Cancel | unloaded status history | eager order relationships | cancel serialization test | integration | PASS |
| Cancel | unreserve failure lost intent | `CANCEL_PENDING` durable retry | cancel retry suite | PostgreSQL | PASS |

## Current contract checks

- B2B batch request is `product_ids` only; `include_unavailable` is absent from current Protocols master.
- B2C sends only that canonical field and enriches omitted products via the service-detail route.
- B2B moderation uses `PRODUCT_BLOCKED` for both soft and internal terminal hard-block states.
