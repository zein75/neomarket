# NeoMarket staging deployment

**Status:** `PASS` for protected runtime deployment; release readiness remains `BLOCKED` by missing QA evidence.

## Deployment record

- Host: `192.168.0.112` (`market-staging`), environment: staging.
- Image release SHA: `7c1951054cf3c4e69b4e1a38769c2ca640da2f89`.
- Compose/Caddy/deployment configuration commit: `772ace6`.
- Deployment was submitted through the forced `neomarket-deploy` SSH command; no Docker socket was granted to `ter0o`.
- Root wrapper wrote the release metadata and completed migrations for B2B, B2C and Admin.
- Deployment output ended with `SMOKE PASS` and `DEPLOY_SUCCESS sha=7c1951054cf3c4e69b4e1a38769c2ca640da2f89`.

## Runtime evidence

- PostgreSQL, Admin PostgreSQL, Redis, Keycloak PostgreSQL, Keycloak, ClamAV and Mailpit are healthy.
- B2C, B2B, Admin, Admin worker, taxonomy worker and recovery worker are running; API readiness returned 200.
- Storefront, Seller and Admin frontends are healthy with `HOSTNAME=0.0.0.0`.
- Gateway is healthy on `127.0.0.1:18080`; the pre-existing demo Nginx on `127.0.0.1:8080` was preserved.
- Caddy HTTPS probes with `--resolve` returned 200 for Storefront/Seller, 307 for the unauthenticated Admin boundary, and 302 for Keycloak.

## Known limits

The smoke test proves service startup, migrations, gateway routing and the negative internal-route boundary. It does not prove authenticated OIDC/MFA, full seller/order/media flows, backup restore, visual acceptance, or production readiness.
