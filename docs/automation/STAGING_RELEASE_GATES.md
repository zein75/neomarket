# NeoMarket staging release gates

**Current status:** `BLOCKED`.

| Gate | Status | Evidence |
|---|---|---|
| Fixed image release and deployment provenance | PASS | image SHA `82e12533be6e06b24a08f9ab2febc13e4589505d`, protected deployment status, `DEPLOY_SUCCESS` |
| Compose static security | PASS | `ci/check_staging_config.py` |
| Runtime health/readiness | PASS | all required services, both workers and gateway healthy; deployment smoke passed |
| Real PostgreSQL/Redis migrations | PASS for current heads | B2B/B2C/Admin migration jobs completed |
| Keycloak availability | PASS | realm imported; container healthy |
| OIDC/MFA/RBAC browser proof | BLOCKED | anonymous boundary is verified; real staff credentials/MFA browser manifests are missing; Keycloak advertises only ACR `0`/`1` |
| Media storage and ClamAV | PARTIAL | ClamAV service is healthy, but `freshclam` still cannot resolve/reach `database.clamav.net` after container-scoped DNS; full upload/quarantine and signature-freshness evidence are not run |
| HTTPS ingress | PASS for routing / PARTIAL for browser | Caddy internal TLS and host routing pass on `82e12533be6e06b24a08f9ab2febc13e4589505d`; CA is trusted by the current Playwright Chromium profile |
| Authenticated Playwright | BLOCKED | no controlled staging Admin test identity/MFA enrollment; anonymous boundary 72/72 only |
| Backup/restore | NOT RUN | external backup target and restore drill absent |
| Three independent clean manifests | BLOCKED | release checker on `cba15c1`: `202` required cases, `0` manifests; [`release-check-cba15c1-20261020.json`](evidence/staging/release-check-cba15c1-20261020.json) |

Production readiness remains false while any mandatory gate is BLOCKED or NOT RUN.
