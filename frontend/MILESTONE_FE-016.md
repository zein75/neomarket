# Milestone FE-016 — frontend CI gate

- Added `.github/workflows/frontend-ci.yml` for PR/push validation of frontend and design-system changes.
- CI uses pinned Node/pnpm versions, frozen lockfile, typecheck, all-app build and design-system asset verification.
- CI fails closed when `frontend/pnpm-lock.yaml` is absent; this is intentional until the workspace lockfile is generated.
- Added a browser-env scan for accidental `NEXT_PUBLIC_*` secrets.

Verification: workflow reviewed statically; GitHub-hosted runner not executed in this environment.
