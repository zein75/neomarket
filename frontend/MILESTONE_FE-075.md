# Milestone FE-075 — authoritative detail availability

- Product detail labels now prioritize the explicit backend `availability` enum over the legacy `in_stock` hint.
- `removed` renders as “Снято с продажи”; only explicit `available` is treated as orderable.
- Unknown/malformed status values are already rejected by the runtime DTO guard.

Verification:

- Storefront typecheck passed.
