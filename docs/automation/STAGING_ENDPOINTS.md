# NeoMarket staging endpoints

**Updated:** 2026-10-20 (runtime verification after deployment)  
**Runtime release:** image SHA `c073e7446d6d639f73644a1b68d2110ed234b325`  
**Gateway:** `127.0.0.1:18080` (the legacy demo Nginx keeps `127.0.0.1:8080`)

| URL / route | Target | Evidence |
|---|---|---|
| `https://storefront.neomarket.test` | Storefront frontend through Caddy | `curl --resolve -k` returned `{"status":"ok"}` on `c073e7446d6d639f73644a1b68d2110ed234b325` |
| `https://seller.neomarket.test` | Seller frontend through Caddy | `curl --resolve -k` returned Seller health response |
| `https://admin.neomarket.test` | Admin frontend through Caddy | `curl --resolve -k` returned Admin health response on `c073e7446d6d639f73644a1b68d2110ed234b325` |
| `https://keycloak.neomarket.test` | Keycloak through Caddy | `curl --resolve -k` returned 302 |
| `127.0.0.1:18080` | Internal Nginx gateway | deployment smoke passed |
| `127.0.0.1:8080` | Existing demo Nginx | preserved; not NeoMarket |
| PostgreSQL, Redis, workers, ClamAV, Mailpit | Docker backend network only | no public host ports |

The Caddy virtual hosts use its internal CA. Browser QA remains blocked until the CA is trusted by the test browser and the four names resolve to `192.168.0.112` in that browser environment. No database, Redis, object-storage, or internal API port is exposed publicly.

## Runtime verification

`STAGING-GW-001` was resolved by the root-owned refresh and gateway-only recreate. Evidence is stored in `docs/automation/evidence/staging/gateway-routes-20261020T115001Z.txt`. The Caddy internal CA still must be trusted by the browser test environment before authenticated OIDC/MFA and visual QA can run.
