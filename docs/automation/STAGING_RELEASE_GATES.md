# NeoMarket staging release gates

**Current status:** `BLOCKED`.

| Gate | Status | Evidence |
|---|---|---|
| Fixed image release and deployment provenance | PASS | image SHA `ee079032cfd234ddd3232c4dfc74fc84b1a5bc22`, protected deployment status, `DEPLOY_SUCCESS` |
| Compose static security | PASS | `ci/check_staging_config.py` |
| Runtime health/readiness | PASS | all required services, both workers and gateway healthy; `smoke-ee07903-20261020.txt` contains `SMOKE PASS` |
| Real PostgreSQL/Redis migrations | PASS for current heads | B2B/B2C/Admin migration jobs completed |
| Keycloak availability | PASS | realm imported; container healthy |
| OIDC/MFA/RBAC browser proof | BLOCKED | anonymous boundary is verified; real staff credentials/MFA browser manifests are missing; Keycloak advertises only ACR `0`/`1` |
| Media storage and ClamAV | PARTIAL | ClamAV is healthy on the private backend plus dedicated egress network; real EICAR detection and clean-file scan passed. `freshclam` reaches the CDN but receives HTTP 403/cooldown, and full upload/quarantine evidence is still not run |
| HTTPS ingress | PASS for routing / PARTIAL for browser | Caddy internal TLS and host routing pass on `ee079032cfd234ddd3232c4dfc74fc84b1a5bc22`; CA is trusted by the current Playwright Chromium profile |
| Authenticated Playwright | BLOCKED | no controlled staging Admin test identity/MFA enrollment; anonymous boundary 72/72 and CSRF 3/3 were last run on code-equivalent `5eb9fc6` before this infra-only commit |
| Backup/restore | NOT RUN | external backup target and restore drill absent |
| Three independent clean manifests | BLOCKED | release checker on `ee07903`: `202` required cases, `0` manifests; [`release-check-ee07903-20261020.json`](evidence/staging/release-check-ee07903-20261020.json) |

Production readiness remains false while any mandatory gate is BLOCKED or NOT RUN.

