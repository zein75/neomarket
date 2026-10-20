# Milestone FE-017 — storefront container

- Added a multi-stage Node 22 Alpine Dockerfile for Next standalone output.
- Runtime runs as non-root `nextjs` user.
- Runtime healthcheck uses the safe `/api/health` endpoint.
- `.dockerignore` excludes node_modules, build caches, logs, secrets and graph artifacts.

Verification: `docker build --file apps/storefront/Dockerfile --tag neomarket-storefront:verify .` passed locally.
The image was started locally, `/api/health` returned `{"status":"ok"}`, and the runtime user was verified as `nextjs` (non-root).
The build reports two non-blocking Autoprefixer warnings for `align-items: end` in the existing design stylesheet; this remains a follow-up compatibility cleanup.
