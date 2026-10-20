# FE-159 — Authoritative cart subtotal and availability

## Delivered

- Live cart totals now render `CartDto.subtotalMinor` instead of recalculating from catalog cards.
- Server-side unavailable reasons are reflected in cart line state and excluded from client-side actions.
- Snapshot state is refreshed on cart load and after item removal; preview remains explicitly local-only.

## Verification

- `pnpm --filter @neomarket/storefront typecheck` — passed.
