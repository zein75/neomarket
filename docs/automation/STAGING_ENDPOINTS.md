# NeoMarket staging endpoints

**Updated:** 2026-10-20 (runtime verification after deployment)  
**Runtime release:** image SHA `dae79147dac0b4d86e4397981e86f7bec10d3faa`
**Gateway:** `127.0.0.1:18080` (the legacy demo Nginx keeps `127.0.0.1:8080`)

| URL / route | Target | Evidence |
|---|---|---|
| `https://storefront.neomarket.test` | Storefront frontend through Caddy | `curl --resolve -k` returned HTTP 200 on `ee079032cfd234ddd3232c4dfc74fc84b1a5bc22` |
| `https://seller.neomarket.test` | Seller frontend through Caddy | `curl --resolve -k` returned Seller health response |
| `https://admin.neomarket.test` | Admin frontend through Caddy | anonymous `/` returns 307 to `/unauthorized`; `/api/health` returns 200; `/api/auth/login` returns a real 307 Keycloak OIDC redirect on `dae79147dac0b4d86e4397981e86f7bec10d3faa` |
| `https://keycloak.neomarket.test` | Keycloak through Caddy | `curl --resolve -k` returned 302 |
| `127.0.0.1:18080` | Internal Nginx gateway | deployment smoke passed |
| `127.0.0.1:8080` | Existing demo Nginx | preserved; not NeoMarket |
| PostgreSQL, Redis, workers, ClamAV, Mailpit | Docker backend network only | no public host ports |

The Caddy virtual hosts use its internal CA. The current Playwright Chromium profile trusts that CA and maps the four names to `192.168.0.112`; authenticated QA remains blocked by the missing controlled Admin test identity/MFA enrollment. No database, Redis, object-storage, or internal API port is exposed publicly.

The Admin server-side OIDC discovery path uses private `keycloak:8080`; the browser redirect uses the public HTTPS Keycloak issuer. Evidence: [`admin-oidc-private-keycloak-dae79147dac0b4d86e4397981e86f7bec10d3faa-20261020T143102Z.json`](evidence/staging/admin-oidc-private-keycloak-dae79147dac0b4d86e4397981e86f7bec10d3faa-20261020T143102Z.json).

## Runtime verification

`STAGING-GW-001` was resolved by the root-owned refresh and gateway-only recreate. Fresh evidence is stored in `docs/automation/evidence/staging/gateway-retry-20261020T181841.txt`. Anonymous browser boundary coverage now runs on deployed SHA `ee079032…`; authenticated OIDC/MFA and visual QA remain open.
