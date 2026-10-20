# Milestone FE-018 — health/readiness

- Added `/api/health` liveness endpoint with `no-store` response.
- Added `/api/ready` readiness endpoint with a one-second bounded B2C health check.
- Readiness returns only `ready`/`not_ready`; internal upstream URL and error details are not exposed.

Verification: syntax check pending; runtime check requires a configured B2C service.
