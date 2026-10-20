# NeoMarket staging release gates

**Current status:** `BLOCKED`.

| Gate | Status | Evidence |
|---|---|---|
| Fixed image release and deployment provenance | PASS for current runtime | live images use SHA `b7e07e79e8f471f664fdc946683f475eae005772`; status: [`status-b7e07e7-20261020.txt`](evidence/staging/status-b7e07e7-20261020.txt). Source HEAD `e7e9010bdec9c72a224a81a1fb57d5bf14e5d941` contains documentation-only changes after that code release. |
| Compose static security | PASS | `ci/check_staging_config.py` |
| Runtime health/readiness | PASS | all required services, both workers and gateway healthy on `b7e07e7`; current status is in `status-b7e07e7-20261020.txt`, and the protected deployment completed without a partial promotion |
| Real PostgreSQL/Redis migrations | PASS for current heads | B2B/B2C/Admin migration jobs completed |
| Keycloak availability | PASS | realm imported; container healthy |
| OIDC/MFA/RBAC browser proof | BLOCKED | anonymous boundary is verified; real staff credentials/MFA browser manifests are missing; Keycloak advertises only ACR `0`/`1` |
| Media storage and ClamAV | PARTIAL | ClamAV is healthy on the private backend plus dedicated egress network; real EICAR detection and clean-file scan passed. `freshclam` reaches the CDN but receives HTTP 403/cooldown, and full upload/quarantine evidence is still not run |
| HTTPS ingress | PASS for routing / PARTIAL for browser | Caddy internal TLS and host routing pass on `b7e07e7`; real HTTPS health/discovery probes are in `https-health-b7e07e7-20261020.txt`; CA is trusted by the current Playwright Chromium profile |
| Authenticated Playwright | BLOCKED | Seller authenticated Chromium sweep on code-equivalent `ee079032` verified 11/11 protected routes; no fresh authenticated run exists for `b7e07e7`; Admin OIDC/MFA, visual comparison and three independent full manifests remain missing |
| Backup/restore | PARTIAL / BLOCKED | isolated local B2C/B2B/Admin restore drill passed with matching counts/checksums and valid Admin audit chain; external backup target, WAL/PITR and RPO/RTO remain absent (`qa-reports/restore-drill/b2b-followup-20261020.json`) |
| Three independent clean manifests | BLOCKED | release checker: `202` required cases, `0` manifests; [`release-check-ee07903-20261020.json`](evidence/staging/release-check-ee07903-20261020.json) |

Production readiness remains false while any mandatory gate is BLOCKED or NOT RUN.

