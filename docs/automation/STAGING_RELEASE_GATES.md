# NeoMarket staging release gates

**Current status:** `BLOCKED`.

Latest checker run on the current source/runtime record is [`release-check-45ebbae-20261020T151000Z.json`](evidence/staging/release-check-45ebbae-20261020T151000Z.json). It reports 202 required cases and zero of the three required independent manifests. The deployed application image is immutable SHA `45ebbae37cb5104decf7a586e767a55cd41cd0cf`.

| Gate | Status | Evidence |
|---|---|---|
| Fixed image release and deployment provenance | PASS for current runtime | live images use SHA `45ebbae37cb5104decf7a586e767a55cd41cd0cf`; status: [`status-45ebbae-20261020.txt`](evidence/staging/status-45ebbae-20261020.txt). |
| Compose static security | PASS | `ci/check_staging_config.py` |
| Runtime health/readiness | PASS | all required services, both workers and gateway healthy on `45ebbae`; current status is in `status-45ebbae-20261020.txt`, and the protected deployment completed without a partial promotion |
| Real PostgreSQL/Redis migrations | PASS for current heads | B2B/B2C/Admin migration jobs completed |
| Keycloak availability | PASS | realm imported; container healthy |
| OIDC/MFA/RBAC browser proof | BLOCKED with fail-closed check PASS | the live Admin page is closed and `/api/auth/login` returns 503 until the explicit MFA claim mapping is configured; discovery advertises only ACR `0`/`1`. Evidence: [`admin-mfa-fail-closed-45ebbae-20261020T150811Z.json`](evidence/staging/admin-mfa-fail-closed-45ebbae-20261020T150811Z.json). Real staff credentials/MFA browser manifests remain unavailable |
| Media storage and ClamAV | PARTIAL | ClamAV is healthy on the private backend plus dedicated egress network; real EICAR detection and clean-file scan passed. `freshclam` reaches the CDN but receives HTTP 403/cooldown, and full upload/quarantine evidence is still not run |
| HTTPS ingress | PASS for routing / PARTIAL for browser | Caddy internal TLS and host routing pass on the current runtime; Admin OIDC redirect evidence is retained in the staging evidence directory; CA is trusted by the current Playwright Chromium profile |
| Authenticated Playwright | BLOCKED | Fresh Seller Chromium sweep on `20cd369` verified 11/11 protected routes with an HttpOnly session and no unexpected 5xx; Admin OIDC/MFA, visual comparison and three independent full manifests remain missing |
| Backup/restore | PARTIAL / BLOCKED | isolated local B2C/B2B/Admin restore drill passed with matching counts/checksums and valid Admin audit chain; external backup target, WAL/PITR and RPO/RTO remain absent (`qa-reports/restore-drill/b2b-followup-20261020.json`) |
| Three independent clean manifests | BLOCKED | current release checker: `202` required cases, `0` manifests; [`release-check-45ebbae-20261020T151000Z.json`](evidence/staging/release-check-45ebbae-20261020T151000Z.json) |

Production readiness remains false while any mandatory gate is BLOCKED or NOT RUN.

