# Milestone FE-028 / AUTH-001 foundation

- Added `SessionResponse` DTO and runtime guard based on `contracts/session.v1.schema.json`.
- Added same-origin `/bff/session` boundary with no-store caching, timeout and fail-closed invalid response handling.
- The BFF forwards only the opaque cookie header; browser tokens are not created or exposed.
- Missing session service returns explicit `503`, never an unauthenticated success disguised as a real session.

Verification: esbuild syntax check — PASS. Full Next/pnpm tests — NOT TESTED because the workspace toolchain is not installed.
