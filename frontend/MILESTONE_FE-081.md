# Milestone FE-081 — session BFF cookie boundary

- Session BFF no longer forwards the browser's complete Cookie header upstream.
- Only `nm_session` and `nm_guest_session` are allowlisted.
- Session errors use `application/problem+json`, `no-store` and request correlation.
- Successful session payloads remain runtime-validated by `isSessionResponse`.

Verification:

- Storefront typecheck passed.
