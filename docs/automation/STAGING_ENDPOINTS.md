# NeoMarket staging endpoints

**Updated:** 2026-10-20 11:10 Asia/Yekaterinburg  
**Runtime release:** image SHA `7c1951054cf3c4e69b4e1a38769c2ca640da2f89`  
**Gateway:** `127.0.0.1:18080` (the legacy demo Nginx keeps `127.0.0.1:8080`)

| URL / route | Target | Evidence |
|---|---|---|
| `https://storefront.neomarket.test` | Storefront frontend through Caddy | `curl --resolve -k` returned 200 |
| `https://seller.neomarket.test` | Seller frontend through Caddy | `curl --resolve -k` returned 200 |
| `https://admin.neomarket.test` | Admin frontend through Caddy | `curl --resolve -k` returned 307 to login boundary |
| `https://keycloak.neomarket.test` | Keycloak through Caddy | `curl --resolve -k` returned 302 |
| `127.0.0.1:18080` | Internal Nginx gateway | deployment smoke passed |
| `127.0.0.1:8080` | Existing demo Nginx | preserved; not NeoMarket |
| PostgreSQL, Redis, workers, ClamAV, Mailpit | Docker backend network only | no public host ports |

The Caddy virtual hosts use its internal CA. Browser QA remains blocked until the CA is trusted by the test browser and the four names resolve to `192.168.0.112` in that browser environment. No database, Redis, object-storage, or internal API port is exposed publicly.
