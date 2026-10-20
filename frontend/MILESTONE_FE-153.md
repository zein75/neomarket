# FE-153 — Product detail SEO contract

## Delivered

- Added dynamic product metadata with canonical URL and fail-closed indexing for invalid, unavailable, or unverified products.
- Added Open Graph fields only when the authoritative product payload passes the shared DTO guard.
- Added grounded schema.org `Product`/`Offer` JSON-LD without fabricated reviews or ratings.
- Relative media is excluded from structured data; only trusted HTTPS product media is emitted.

## Verification

- `pnpm --filter @neomarket/storefront typecheck` — passed.
