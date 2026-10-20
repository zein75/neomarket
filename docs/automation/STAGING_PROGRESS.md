# Staging progress

**Updated:** 2026-10-20 (registry auth and first deployment verified)

| Phase | Result | Evidence |
|---|---|---|
| S0 host audit | DONE | `STAGING_INFRA_AUDIT.md`, `STAGING_FULLSTACK_QA.md` |
| S1 restricted deployment path | BOOTSTRAPPED, wrapper smoke-tested | `deploy/staging/bootstrap/`; SHA request reached root wrapper |
| S2 filesystem/secrets | PARTIAL | generated base env and root-only GHCR credential config are present; corrected compose-path scripts from `617a117` still require one restricted bootstrap refresh |
| S3 Compose runtime | IMAGE PULL PASS, runtime BLOCKED | SHA-tagged API/frontend images pulled successfully; deployment stopped at compose-path mismatch, fixed in `617a117` |
| S4 ingress/HTTPS | BLOCKED | internal hostnames reserved; existing Caddy is default HTTP page; TLS/CA not installed |
| S5 migrations/integration | BLOCKED BEFORE MIGRATION | PostgreSQL/Redis containers became healthy; migration stage was not reached because of the helper path error |
| S6 Keycloak/OIDC/MFA | COMPOSE PREPARED, runtime NOT RUN | Keycloak/PostgreSQL/realm template added; root refresh and TLS still required |
| S7 media/antivirus | Compose prepared with ClamAV; runtime NOT RUN | staging Compose and static check |
| S8 workers/events | NOT RUN | no runtime deployment |
| S9 CI/CD | workflow patched to request restricted deployment; NOT RUN | `.github/workflows/neomarket-staging.yml` |
| S10 browser QA | BLOCKED | no staging URL/authenticated storage state |
| S13 backup/restore | NOT RUN | external backup target not configured |
| S14 security audit | BLOCKED | runtime evidence unavailable |

Current release status is **BLOCKED**. Do not mark acceptance scenarios PASS until a fixed Git commit is deployed and three independent Playwright manifests plus backend evidence exist.
