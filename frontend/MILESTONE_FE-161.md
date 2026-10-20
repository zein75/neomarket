# FE-161 — Checkout pending form contract

## Delivered

- Checkout form now exposes pending state through `aria-busy` and a polite status region.
- Inputs, back navigation, and submit are disabled during cart validation.
- CTA text changes to the exact active operation instead of allowing duplicate submits.
- Added a small design-system state stylesheet without changing unsupported payment behavior.

## Verification

- `pnpm --filter @neomarket/storefront typecheck` — passed.
