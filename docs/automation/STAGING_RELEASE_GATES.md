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
| Media storage and ClamAV | PARTIAL | ClamAV healthy; full upload/quarantine flow not run |
| HTTPS ingress | PASS for routing / PARTIAL for browser | Caddy internal TLS and host routing pass on `82e12533be6e06b24a08f9ab2febc13e4589505d`; CA is trusted by the current Playwright Chromium profile |
| Authenticated Playwright | BLOCKED | no controlled staging Admin test identity/MFA enrollment; anonymous boundary 72/72 only |
| Backup/restore | NOT RUN | external backup target and restore drill absent |
| Three independent clean manifests | BLOCKED | release checker: `202` required cases, `0` manifests; [`release-check-20261020T1813Z.json`](evidence/staging/release-check-20261020T1813Z.json) |

Production readiness remains false while any mandatory gate is BLOCKED or NOT RUN.
