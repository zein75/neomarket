# Milestone FE-032 — guest cart BFF boundary

- Added `/api/storefront/cart` GET/DELETE same-origin route.
- Guest identity is an opaque, HttpOnly `nm_guest_session` UUID cookie; it is forwarded only as `X-Session-Id` to the configured B2C upstream.
- Added `/api/auth/csrf` synchronizer token endpoint for destructive cart operations.
- DELETE fails closed on missing/mismatched CSRF token; all responses are `no-store` and bounded by a timeout.
- No browser token or direct browser-to-FastAPI call is introduced.

Verification: syntax check pending in the next toolchain run; full integration test requires a running B2C service with PostgreSQL/Redis.
