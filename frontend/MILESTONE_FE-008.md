# Milestone FE-008 / FE-011 / FE-019

## Scope

Workspace foundation, three app shells, shared DTO/auth/design tokens and the first responsive storefront slice (catalog, search, cart and orders entry).

## Files changed

- `apps/storefront`: Next.js app shell, metadata, loading/error states, responsive brutalist storefront.
- `apps/storefront/app/bff/catalog/route.ts`: server-only, fixed-origin catalog BFF route with timeout and query allowlist.
- `apps/seller`, `apps/admin`: isolated private app shells with `noindex` metadata.
- `packages/ui`, `packages/api-types`, `packages/api-client`, `packages/auth`: shared foundations.
- `apps/storefront/public/design-system`: Stitch reference images copied from `docs/design-system`.

## Verification

- `npx --yes esbuild@0.24.0 ...Storefront.tsx` — PASS (TSX syntax).
- `npx --yes esbuild@0.24.0 ...app/*.tsx` — PASS (TSX syntax).
- shared package syntax check with esbuild — PASS.
- server-only catalog BFF route syntax check with esbuild — PASS.
- `pnpm -r typecheck` / `pnpm -r build` — NOT TESTED: pnpm is not installed in the environment and the lockfile is intentionally not generated yet.

## Security and reliability

- UI does not expose tokens or call internal FastAPI services directly.
- BFF never accepts a browser-supplied upstream URL; only `NEOMARKET_B2C_URL` is used and catalog query keys are allowlisted.
- `@neomarket/api-client` is an allowlisted catalog operation placeholder; unknown outcomes are errors, not success states.
- The current storefront is explicitly `preview / read-only`; product fixtures are visual-only until the proposed BFF contract is implemented and verified.
- Cart totals exclude removed/unavailable lines, matching the reviewed backend behavior.

## Known blockers before next slice

- Agree and implement BFF `/catalog`, session and CSRF contracts from `contracts/bff.openapi.yaml`.
- Generate and commit pnpm lockfile using the selected Node LTS/pnpm versions.
- Replace visual fixtures with server-fetched DTOs, then add Vitest/Playwright contract and accessibility coverage.

Decision: GO TO NEXT STEP after BFF contract and package toolchain are available; not production-ready.
