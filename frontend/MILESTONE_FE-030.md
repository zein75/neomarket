# Milestone FE-030 — buyer auth UI boundary

- Added storefront `/login` and `/register` pages.
- Forms use accessible labels, autocomplete, password constraints, disabled pending submit and recoverable blocked state.
- No browser token, fake session or success response is created; submission remains blocked until the BFF auth contract is available.
- Styling follows the shared NeoMarket design-system tokens and primitives.

Verification: esbuild syntax check — PASS. Browser/E2E and full workspace build — NOT TESTED until pnpm and the auth backend contract are available.
