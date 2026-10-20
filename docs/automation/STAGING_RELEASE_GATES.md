# NeoMarket staging release gates

**Current status:** `BLOCKED`.

Latest checker run on deployed SHA `0fcb935bfd14eba6eaa197898bf865e21eddfbd4`: [`release-check-0fcb935-20261020T194719.json`](evidence/staging/release-check-0fcb935-20261020T194719.json). It reports 202 required cases and zero of the three required independent manifests.

| Gate | Status | Evidence |
|---|---|---|
| Fixed image release and deployment provenance | PASS for current runtime | live images use SHA `0fcb935bfd14eba6eaa197898bf865e21eddfbd4`; status: [`status-0fcb935-20261020T194454.txt`](evidence/staging/status-0fcb935-20261020T194454.txt). |
| Compose static security | PASS | `ci/check_staging_config.py` |
| Runtime health/readiness | PASS | all required services, both workers and gateway healthy on `0fcb935`; current status is in `status-0fcb935-20261020T194454.txt`, and the protected deployment completed without a partial promotion |
| Real PostgreSQL/Redis migrations | PASS for current heads | B2B/B2C/Admin migration jobs completed |
| Keycloak availability | PASS | realm imported; container healthy |
| OIDC/MFA/RBAC browser proof | BLOCKED | OIDC discovery and 307 redirect pass through the private Keycloak service; real staff credentials/MFA browser manifests are missing and ACR/step-up mapping remains not configured |
| Media storage and ClamAV | PARTIAL | ClamAV is healthy on the private backend plus dedicated egress network; real EICAR detection and clean-file scan passed. `freshclam` reaches the CDN but receives HTTP 403/cooldown, and full upload/quarantine evidence is still not run |
| HTTPS ingress | PASS for routing / PARTIAL for browser | Caddy internal TLS and host routing pass on `0fcb935`; Admin OIDC redirect evidence is in [`admin-oidc-0fcb935-20261020T194621.json`](evidence/staging/admin-oidc-0fcb935-20261020T194621.json); CA is trusted by the current Playwright Chromium profile |
| Authenticated Playwright | BLOCKED | Fresh Seller Chromium sweep on `20cd369` verified 11/11 protected routes with an HttpOnly session and no unexpected 5xx; Admin OIDC/MFA, visual comparison and three independent full manifests remain missing |
| Backup/restore | PARTIAL / BLOCKED | isolated local B2C/B2B/Admin restore drill passed with matching counts/checksums and valid Admin audit chain; external backup target, WAL/PITR and RPO/RTO remain absent (`qa-reports/restore-drill/b2b-followup-20261020.json`) |
| Three independent clean manifests | BLOCKED | current release checker: `202` required cases, `0` manifests; [`release-check-20261020T1448Z.json`](evidence/staging/release-check-20261020T1448Z.json) |

Production readiness remains false while any mandatory gate is BLOCKED or NOT RUN.

