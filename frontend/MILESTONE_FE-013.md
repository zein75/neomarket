# Milestone FE-013 / FE-021

Implemented a guarded live catalog path:

- browser requests only same-origin `/bff/catalog`;
- runtime flag `NEXT_PUBLIC_ENABLE_LIVE_CATALOG` defaults to `false`;
- response is normalized at the boundary and rejects malformed items;
- loading and recoverable error states include retry;
- preview fixtures remain an explicit fallback until BFF contract integration is verified.

Verification: esbuild TSX syntax check — PASS. Full pnpm typecheck/build — NOT TESTED because pnpm and lockfile are not installed.
