# FE-164 — Preserve delisted cart lines

## Delivered

- Authoritative cart lines are now unioned with the current catalog.
- A product missing from the public catalog remains visible by its server-provided name and is marked unavailable.
- Unavailable reasons are translated to plain Russian labels; no price or availability is invented for missing products.
- Such lines remain excluded from the subtotal and cannot be added to checkout.

## Verification

- `pnpm --filter @neomarket/storefront typecheck` — passed.
