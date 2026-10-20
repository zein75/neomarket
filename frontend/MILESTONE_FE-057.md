# Milestone FE-057 — BFF request correlation

- Catalog and guest-cart BFF responses now return the sanitized `X-Request-ID` used for the upstream call.
- 503 problem responses include the same correlation id while remaining `no-store` and free of internal service details.
- Upstream calls continue to receive only allowlisted headers and bounded timeouts.

Verification:

- Storefront typecheck passed.
