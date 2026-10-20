# Staging progress

**Updated:** 2026-10-20 (runtime rollout and health-gate fixes)

| Phase | Result | Evidence |
|---|---|---|
| S0 host audit | DONE | `STAGING_INFRA_AUDIT.md`, `STAGING_FULLSTACK_QA.md` |
| S1 restricted deployment path | BOOTSTRAPPED, wrapper smoke-tested | `deploy/staging/bootstrap/`; SHA request reached root wrapper |
| S2 filesystem/secrets | BOOTSTRAPPED | generated base env and root-only GHCR credential config are present; deployment user has only fixed-SHA/status commands |
| S3 Compose runtime | PARTIAL, current rollout BLOCKED | `1ceba9f` API images and Keycloak pulled; API/admin/worker readiness passed, but ClamAV/Mailpit failed startup and old frontend images reported unhealthy. Compose fixes are in `40ffdc1`; frontend image healthcheck fixes are in `e4249b7`. Root-owned compose refresh is pending. |
| S4 ingress/HTTPS | BLOCKED | internal hostnames reserved; existing Caddy is default HTTP page; TLS/CA not installed |
| S5 migrations/integration | PASS for current API schema | B2B/B2C/Admin migrations completed through current heads; API readiness and worker health passed for `1ceba9f`; PostgreSQL/Redis healthy |
| S6 Keycloak/OIDC/MFA | Keycloak healthy, browser proof NOT RUN | Keycloak and dedicated PostgreSQL became healthy; public ingress and real browser OIDC/MFA remain unverified |
| S7 media/antivirus | BLOCKED at ClamAV startup | ClamAV service restarted with exit 1 under the old root compose; a minimal startup fix is included in `40ffdc1` |
| S8 workers/events | API workers healthy, full event QA NOT RUN | admin-worker, taxonomy worker and recovery worker were started; full retry/DLQ evidence remains outstanding |
| S9 CI/CD | CI PASS, protected deploy path verified | runs `39405875211` and `39406495189` passed verify/integration/build; deploy remains manually authorized by the restricted wrapper |
| S10 browser QA | BLOCKED | no staging URL/authenticated storage state |
| S13 backup/restore | NOT RUN | external backup target not configured |
| S14 security audit | BLOCKED | runtime evidence unavailable |

Current release status is **BLOCKED**. Do not mark acceptance scenarios PASS until `e4249b7` is deployed after the root-owned compose refresh, public ingress is configured, and three independent Playwright manifests plus backend evidence exist.
