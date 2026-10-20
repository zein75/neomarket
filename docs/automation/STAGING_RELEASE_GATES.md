# NeoMarket staging release gates

**Current status:** `BLOCKED`.

| Gate | Status | Evidence |
|---|---|---|
| Fixed image release and deployment provenance | PASS for current runtime | live images use SHA `872b0a1bcfcdac48fb347420502ac92596d0151b`; status: [`status-872b0a1-20261020.txt`](evidence/staging/status-872b0a1-20261020.txt). Source HEAD `35ebe3a19eec7e524d2a22d7f233c624eb0592ac` is not deployed because its immutable `admin-frontend` image is not published. |
| Compose static security | PASS | `ci/check_staging_config.py` |
| Runtime health/readiness | PASS | all required services, both workers and gateway healthy on `872b0a1`; current status is in `status-872b0a1-20261020.txt`, and the deployed smoke run returned `SMOKE PASS` |
| Real PostgreSQL/Redis migrations | PASS for current heads | B2B/B2C/Admin migration jobs completed |
| Keycloak availability | PASS | realm imported; container healthy |
| OIDC/MFA/RBAC browser proof | BLOCKED | anonymous boundary is verified; real staff credentials/MFA browser manifests are missing; Keycloak advertises only ACR `0`/`1` |
| Media storage and ClamAV | PARTIAL | ClamAV is healthy on the private backend plus dedicated egress network; real EICAR detection and clean-file scan passed. `freshclam` reaches the CDN but receives HTTP 403/cooldown, and full upload/quarantine evidence is still not run |
| HTTPS ingress | PASS for routing / PARTIAL for browser | Caddy internal TLS and host routing pass; current runtime status is `872b0a1`; CA is trusted by the current Playwright Chromium profile |
| Authenticated Playwright | BLOCKED | Seller authenticated Chromium sweep on code-equivalent `ee079032` verified 11/11 protected routes; no fresh authenticated run exists for `872b0a1`; Admin OIDC/MFA, visual comparison and three independent full manifests remain missing |
| Backup/restore | PARTIAL / BLOCKED | isolated local B2C/B2B/Admin restore drill passed with matching counts/checksums and valid Admin audit chain; external backup target, WAL/PITR and RPO/RTO remain absent (`qa-reports/restore-drill/b2b-followup-20261020.json`) |
| Three independent clean manifests | BLOCKED | release checker: `202` required cases, `0` manifests; [`release-check-ee07903-20261020.json`](evidence/staging/release-check-ee07903-20261020.json) |

Production readiness remains false while any mandatory gate is BLOCKED or NOT RUN.

