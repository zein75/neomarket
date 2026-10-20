# FE-150 — Product detail page from NeoMarket product-screen reference

## Delivered

- Rebuilt `ProductDetail` around the supplied NeoMarket Brutalist product-screen reference.
- Added responsive gallery/stage, breadcrumbs, operational availability tags, SKU identity, quantity control, price summary, CTA, commerce guardrails, tab navigation, and lower information panels.
- Kept the page contract-safe: only `ProductDetailDto` fields are rendered as product facts; unsupported specifications, documents, and reviews are explicitly marked unavailable instead of invented.
- Replaced inline-script behavior with React state and accessible controls.

## Verification

- `pnpm --filter @neomarket/storefront typecheck` — passed.
- `pnpm --filter @neomarket/storefront build` — passed.
