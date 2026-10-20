# NeoMarket staging release gates

**Current status:** `BLOCKED`.

| Gate | Status | Evidence |
|---|---|---|
| Fixed image release and deployment provenance | PASS | image SHA `7c195105…`, deployment wrapper log, `DEPLOY_SUCCESS` |
| Compose static security | PASS | `ci/check_staging_config.py` |
| Runtime health/readiness | PASS | all required services healthy; deployment smoke passed |
| Real PostgreSQL/Redis migrations | PASS for current heads | B2B/B2C/Admin migration jobs completed |
| Keycloak availability | PASS | realm imported; container healthy |
| OIDC/MFA/RBAC browser proof | BLOCKED | trusted CA and authenticated browser manifests missing |
| Media storage and ClamAV | PARTIAL | ClamAV healthy; full upload/quarantine flow not run |
| HTTPS ingress | PARTIAL | Caddy internal TLS responds; client CA trust not installed |
| Authenticated Playwright | BLOCKED | browser environment cannot yet trust Caddy CA |
| Backup/restore | NOT RUN | external backup target and restore drill absent |
| Three independent clean manifests | BLOCKED | not run |

Production readiness remains false while any mandatory gate is BLOCKED or NOT RUN.
