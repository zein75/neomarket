# FE-157 — Category detail SEO contract

## Delivered

- Added dynamic category title, description, canonical URL, and fail-closed robots policy.
- Added Open Graph metadata only for validated category DTOs.
- Added grounded `CollectionPage` JSON-LD with optional authoritative item count.

## Verification

- `pnpm --filter @neomarket/storefront typecheck` — passed.
