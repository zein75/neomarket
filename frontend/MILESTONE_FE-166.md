# FE-166 — Contract-safe catalog add action

## Delivered

- Product cards now receive an explicit `mutationsEnabled` capability.
- Live catalog no longer pretends to add items locally while the BFF lacks a POST add-item route.
- Preview keeps the local fixture interaction; live mode explains why the action is unavailable.

## Verification

- `pnpm --filter @neomarket/storefront typecheck` — passed.
