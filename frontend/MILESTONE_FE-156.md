# FE-156 — Category detail resilient states

## Delivered

- Added category loading skeleton with `aria-busy` and reduced-motion behavior.
- Added bounded retry for safe category GET failures.
- Added explicit fallback navigation to catalog and preserved authoritative-data-only rendering.

## Verification

- `pnpm --filter @neomarket/storefront typecheck` — passed.
