# Milestone FE-053 — clean frontend release context

- Added frontend-specific ignore rules for dependencies, Next.js output, incremental compiler state, coverage and local secrets.
- Extended the Docker build context exclusions with `tsconfig.tsbuildinfo`.
- This keeps design-system assets and source contracts in audit archives while excluding generated caches.

Verification:

- `git check-ignore -v` confirms `node_modules`, `.next` and `tsconfig.tsbuildinfo` are ignored.
