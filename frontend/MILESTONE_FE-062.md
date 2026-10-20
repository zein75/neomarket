# Milestone FE-062 — catalog BFF error contract

- Catalog BFF configuration, timeout and upstream failures now use `application/problem+json`.
- Responses include request correlation and `no-store` cache policy while hiding upstream implementation details.
- Successful proxy responses preserve the upstream media type and status for typed client handling.

Verification:

- Storefront typecheck passed.
