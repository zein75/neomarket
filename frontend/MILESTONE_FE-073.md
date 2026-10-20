# Milestone FE-073 — CI least privilege and dependency gate

- Frontend workflow now declares explicit read-only permissions and denies package/security-event writes.
- Checkout no longer persists the GitHub token in the workspace.
- Added `pnpm audit --audit-level=high` before typecheck/build.
- Existing design-system presence and browser-secret checks remain mandatory.

Note: action references are still version tags (`@v4`); immutable SHA pinning remains a repository-level supply-chain follow-up before production release.
