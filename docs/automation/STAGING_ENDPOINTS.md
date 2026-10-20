# NeoMarket staging endpoints

**Updated:** 2026-10-20 (runtime verification after deployment)  
**Runtime release:** image SHA `c073e7446d6d639f73644a1b68d2110ed234b325`  
**Gateway:** `127.0.0.1:18080` (the legacy demo Nginx keeps `127.0.0.1:8080`)

| URL / route | Target | Evidence |
|---|---|---|
| `https://storefront.neomarket.test` | Storefront frontend through Caddy | Host route currently serves Admin health response; **DEFECT STAGING-GW-001** |
| `https://seller.neomarket.test` | Seller frontend through Caddy | `curl --resolve -k` returned Seller health response |
| `https://admin.neomarket.test` | Admin frontend through Caddy | Host route currently serves Storefront health response; **DEFECT STAGING-GW-001** |
| `https://keycloak.neomarket.test` | Keycloak through Caddy | `curl --resolve -k` returned 302 |
| `127.0.0.1:18080` | Internal Nginx gateway | deployment smoke passed |
| `127.0.0.1:8080` | Existing demo Nginx | preserved; not NeoMarket |
| PostgreSQL, Redis, workers, ClamAV, Mailpit | Docker backend network only | no public host ports |

The Caddy virtual hosts use its internal CA. Browser QA remains blocked until the CA is trusted by the test browser and the four names resolve to `192.168.0.112` in that browser environment. No database, Redis, object-storage, or internal API port is exposed publicly.

## Open routing defect

`STAGING-GW-001` was reproduced with real HTTPS requests on the deployed release. The root-owned refresh previously updated Compose and Caddy but left the bind-mounted gateway `nginx.conf` stale. Commit `16edf0a` makes the refresh install that file; commit `8cf801c` makes the root deployment wrapper force-recreate only the gateway so the file is loaded. The fix is awaiting the one-time root refresh on staging, after which the three frontend health probes must be repeated.
