# Milestone FE-011 — shared UI foundation

- Added `@neomarket/ui` primitives: `Button`, `StatusBadge`, `Price`.
- Added semantic variants, keyboard-visible focus and disabled states.
- Added storefront primitive styles using the design-system tokens and hard-edge shadow language.
- Kept UI package free from backend roles, secrets and domain CRUD.

Verification: esbuild syntax check — PASS. Full workspace typecheck/build — NOT TESTED until pnpm and the lockfile are installed.
