# NeoMarket staging deployment

**Status:** `PASS` for protected runtime deployment; release readiness remains `BLOCKED` by missing QA evidence.

## Deployment record

### Authoritative current runtime (2026-10-20)

- Current deployed application image SHA: `45ebbae37cb5104decf7a586e767a55cd41cd0cf`.
- All application services, workers, gateway and Keycloak are healthy; see [`status-45ebbae-20261020.txt`](evidence/staging/status-45ebbae-20261020.txt).
- The older deployment records below remain historical evidence and are not the current image.

- Host: `192.168.0.112` (`market-staging`), environment: staging.
- Image release SHA: `ee079032cfd234ddd3232c4dfc74fc84b1a5bc22`.
- Compose/Caddy/deployment configuration commit: `ee07903` (full SHA above).
- Deployment was submitted through the forced `neomarket-deploy` SSH command; no Docker socket was granted to `ter0o`.
- Root wrapper wrote the release metadata and completed migrations for B2B, B2C and Admin.
- Deployment output ended with `SMOKE PASS` and `DEPLOY_SUCCESS sha=ee079032cfd234ddd3232c4dfc74fc84b1a5bc22`.

## Runtime evidence

- PostgreSQL, Admin PostgreSQL, Redis, Keycloak PostgreSQL, Keycloak, ClamAV and Mailpit are healthy.
- B2C, B2B, Admin, Admin worker, taxonomy worker and recovery worker are running; API readiness returned 200.
- Storefront, Seller and Admin frontends are healthy with `HOSTNAME=0.0.0.0`.
- Gateway is healthy on `127.0.0.1:18080`; the pre-existing demo Nginx on `127.0.0.1:8080` was preserved.
- Caddy HTTPS probes with `--resolve` returned 200 for Storefront/Seller, 307 for the unauthenticated Admin boundary, and 302 for Keycloak.

Latest protected status evidence: [`status-20261020T131059Z.txt`](evidence/staging/status-20261020T131059Z.txt). Gateway/API route evidence: [`gateway-routes-20261020T131059Z.txt`](evidence/staging/gateway-routes-20261020T131059Z.txt).

## Known limits

The smoke test proves service startup, migrations, gateway routing and the negative internal-route boundary. It does not prove authenticated OIDC/MFA, full seller/order/media flows, backup restore, visual acceptance, or production readiness.
