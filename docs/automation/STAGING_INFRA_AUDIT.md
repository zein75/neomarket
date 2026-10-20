# NeoMarket staging infrastructure audit

**Date:** 2026-10-20  
**Environment:** `market-staging` / `192.168.0.112`  
**Status:** `PASS` for protected runtime bootstrap; release gates remain `BLOCKED`.

## Observed host

The current protected runtime is pinned to application image SHA `b0fd2323d8fa5c6df166018f0e5f7c0cfdb4c565`; older deployment SHAs in this audit are historical evidence.

- Ubuntu 26.04.1 LTS, kernel `7.0.0-38-generic`, x86_64.
- 12 CPU threads; 15 GiB RAM (about 13 GiB available); 4 GiB unused swap.
- Root filesystem: 468 GiB ext4, about 343 GiB free.
- Docker Engine 29.9.1, Compose v5.6.0; Docker and containerd are active.
- Network interface `enp4s0`: `192.168.0.112/24`.
- Listeners observed: SSH `22`, Caddy `80/443`, loopback Nginx `8080`, NeoMarket gateway `18080`, plus host-local system services.

## Access boundary

The SSH account `ter0o` is not in the Docker group. Docker socket access returns permission denied and `sudo -n` is unavailable. No LXD, Docker socket, or other privilege escalation was used. Firewall rules and effective SSH policy require an approved privileged inspection. `/etc/neomarket` is root-only; the protected runtime is under `/opt/neomarket-staging` and is accessed through the forced `neomarket-deploy` key.

## Existing services and conflict risks

- Caddy serves the private staging virtual hosts on ports 80/443 with its local CA.
- A demo Nginx container is bound to `127.0.0.1:8080`; its `/health` endpoint returns 404 for the expected internal hostnames.
- The protected NeoMarket B2C/B2B/Admin APIs, frontends, workers, Keycloak and ClamAV runtime are deployed and healthy on the latest pinned release.
- Port 80 and loopback 8080 must not be replaced until the owner approves the new ingress and preserves the demo configuration if it is still needed.

## Capacity assessment

The host has enough disk and CPU for a resource-capped staging stack, but 15 GiB RAM is tight for PostgreSQL, three APIs, three frontends, workers, Keycloak, and ClamAV simultaneously. The Compose limits must remain enforced and memory pressure must be measured after deployment. S3/object storage and SMTP remain external integration decisions; no fake providers are permitted.

## Protected runtime result

The bounded bootstrap and refresh path are installed. It creates a root-owned deployment wrapper and a restricted `neomarket-deploy` SSH account; it does not add the account to `docker`, install arbitrary sudo, replace the demo Nginx, or expose application secrets. The latest protected deployment is SHA `ee079032cfd234ddd3232c4dfc74fc84b1a5bc22`.

## Evidence gaps

Firewall rules and effective SSH configuration still require the owner-run verification command. Protected status confirms current container inventory and health without exposing secrets.

## Runtime update — 2026-10-20 11:10

The protected staging bootstrap and deployment path are active. The legacy demo Nginx listener on `127.0.0.1:8080` was preserved; NeoMarket gateway uses `127.0.0.1:18080`. The fixed-SHA deployment for image `ee079032cfd234ddd3232c4dfc74fc84b1a5bc22` completed migrations and smoke checks. All required containers reported healthy, and Caddy HTTPS probes reached the four staging virtual hosts. Anonymous browser boundaries pass on the immediately preceding code-equivalent SHA; authenticated OIDC/MFA, backup/restore and full end-to-end evidence remain open.
