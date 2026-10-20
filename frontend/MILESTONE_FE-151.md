# FE-151 — Shared quantity stepper primitive

## Delivered

- Added `QuantityStepper` to `@neomarket/ui` with bounded values, disabled state, numeric input, and accessible labels.
- Reused the primitive in the product detail purchase panel instead of keeping a page-specific quantity control.
- Preserved the NeoMarket hard-border/shadow styling through the existing storefront token class.

## Verification

- `pnpm --filter @neomarket/ui typecheck` — passed.
- `pnpm --filter @neomarket/storefront typecheck` — passed.
