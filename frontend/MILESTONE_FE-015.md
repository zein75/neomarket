# Milestone FE-015 — telemetry and redaction foundation

- Added `@neomarket/telemetry` with request ID validation/generation, sensitive header redaction and safe event attributes.
- Catalog and cart BFF routes now propagate bounded request IDs upstream.
- No cookies, authorization tokens, CSRF tokens or password-like attributes are emitted by the helper.
- Provider integration is intentionally deferred until the observability owner selects the production backend.

Verification: typecheck/build pending after lockfile update.
