# FE-165 — Cart validity warning

## Delivered

- Cart now surfaces `CartDto.isValid === false` as an accessible warning.
- The warning explains that price, availability, or quantity changed and that checkout will revalidate.
- Existing authoritative subtotal and unavailable-line behavior are preserved.

## Verification

- `pnpm --filter @neomarket/storefront typecheck` — passed.
