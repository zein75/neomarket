# Milestone FE-061 — BFF problem responses

- Cart clear, item removal and cart validation failures now use `application/problem+json`.
- Problem responses preserve bounded information: stable type/title/status, optional request ID and no upstream internals.
- All mutation/validation errors remain `Cache-Control: no-store`.

Verification:

- Storefront typecheck passed.
