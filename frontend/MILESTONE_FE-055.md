# Milestone FE-055 — browser security headers

- Added baseline security headers to Storefront, Seller and Admin Next runtimes.
- Headers include report-only CSP, `Referrer-Policy`, `X-Content-Type-Options`, `X-Frame-Options` and restrictive `Permissions-Policy`.
- CSP keeps the current preview compatible while collecting violations before production enforcement; no remote image hosts are enabled in Next config.
- `poweredByHeader` remains disabled on Storefront and private apps stay no-store/dynamic.

Verification:

- Full frontend recursive typecheck passed.
- Full frontend recursive production build passed for all three apps.
