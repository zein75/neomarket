# NeoMarket staging release gates

**Current status:** `BLOCKED`.

| Gate | Status | Evidence |
|---|---|---|
| Fixed image release and deployment provenance | PASS for current runtime | live images use SHA `d30c5d843f741213db7d11278bb528c586655b90`; status: [`status-d30c5d8-20261020.txt`](evidence/staging/status-d30c5d8-20261020.txt). |
| Compose static security | PASS | `ci/check_staging_config.py` |
| Runtime health/readiness | PASS | all required services, both workers and gateway healthy on `d30c5d8`; current status is in `status-d30c5d8-20261020.txt`, and the protected deployment completed without a partial promotion |
| Real PostgreSQL/Redis migrations | PASS for current heads | B2B/B2C/Admin migration jobs completed |
| Keycloak availability | PASS | realm imported; container healthy |
| OIDC/MFA/RBAC browser proof | BLOCKED | anonymous boundary is verified; real staff credentials/MFA browser manifests are missing; Keycloak advertises only ACR `0`/`1` |
| Media storage and ClamAV | PARTIAL | ClamAV is healthy on the private backend plus dedicated egress network; real EICAR detection and clean-file scan passed. `freshclam` reaches the CDN but receives HTTP 403/cooldown, and full upload/quarantine evidence is still not run |
| HTTPS ingress | PASS for routing / PARTIAL for browser | Caddy internal TLS and host routing pass on `d30c5d8`; real HTTPS health/discovery probes are in `https-health-d30c5d8-20261020.txt`; CA is trusted by the current Playwright Chromium profile |
| Authenticated Playwright | BLOCKED | Fresh Seller Chromium sweep on `20cd369` verified 11/11 protected routes with an HttpOnly session and no unexpected 5xx; Admin OIDC/MFA, visual comparison and three independent full manifests remain missing |
| Backup/restore | PARTIAL / BLOCKED | isolated local B2C/B2B/Admin restore drill passed with matching counts/checksums and valid Admin audit chain; external backup target, WAL/PITR and RPO/RTO remain absent (`qa-reports/restore-drill/b2b-followup-20261020.json`) |
| Three independent clean manifests | BLOCKED | current release checker: `202` required cases, `0` manifests; [`release-check-71fdfbf-20261020.json`](evidence/staging/release-check-71fdfbf-20261020.json) |

Production readiness remains false while any mandatory gate is BLOCKED or NOT RUN.

