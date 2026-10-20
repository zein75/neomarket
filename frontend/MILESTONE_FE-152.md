# FE-152 — Product detail loading and recoverable error states

## Delivered

- Added a token-based product skeleton with `aria-busy`, polite loading status, and reduced-motion fallback.
- Added a bounded retry action for recoverable product GET failures.
- Added a safe fallback navigation to the catalog and made clear that stale/cache data is not substituted for authoritative product data.

## Verification

- `pnpm --filter @neomarket/storefront typecheck` — passed.
