# Milestone FE-077 — storefront production verification

- Storefront production build passed after currency-aware DTO and availability changes.
- Next.js generated 28 routes, including dynamic product/category and cart BFF endpoints.
- Static public pages and dynamic API/detail routes remain correctly separated.

Verification:

- `pnpm --filter @neomarket/storefront build` passed.
