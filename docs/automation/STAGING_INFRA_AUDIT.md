# NeoMarket staging infrastructure audit

**Date:** 2026-10-20  
**Environment:** `market-staging` / `192.168.0.112`  
**Status:** `BLOCKED` for deployment; S0 read-only audit complete.

## Observed host

- Ubuntu 26.04.1 LTS, kernel `7.0.0-38-generic`, x86_64.
- 12 CPU threads; 15 GiB RAM (about 13 GiB available); 4 GiB unused swap.
- Root filesystem: 468 GiB ext4, about 343 GiB free.
- Docker Engine 29.9.1, Compose v5.6.0; Docker and containerd are active.
- Network interface `enp4s0`: `192.168.0.112/24`.
- Listeners observed: SSH `22`, Caddy `80`, loopback Nginx `8080`, plus host-local system services.

## Access boundary

The SSH account `ter0o` is not in the Docker group. Docker socket access returns permission denied and `sudo -n` is unavailable. No LXD, Docker socket, or other privilege escalation was used. Firewall rules and effective SSH policy require an approved privileged inspection. `/etc/neomarket` is root-only; `/opt/neomarket-staging` does not exist.

## Existing services and conflict risks

- Caddy currently serves the default static page on port 80.
- A demo Nginx container is bound to `127.0.0.1:8080`; its `/health` endpoint returns 404 for the expected internal hostnames.
- No NeoMarket B2C/B2B/Admin APIs, frontends, workers, Keycloak, object storage, or antivirus runtime were observed.
- Port 80 and loopback 8080 must not be replaced until the owner approves the new ingress and preserves the demo configuration if it is still needed.

## Capacity assessment

The host has enough disk and CPU for a resource-capped staging stack, but 15 GiB RAM is tight for PostgreSQL, three APIs, three frontends, workers, Keycloak, and ClamAV simultaneously. The Compose limits must remain enforced and memory pressure must be measured after deployment. S3/object storage and SMTP remain external integration decisions; no fake providers are permitted.

## Required privileged changes

Run the bounded bootstrap in [`deploy/staging/bootstrap/README.md`](../../deploy/staging/bootstrap/README.md) once as the server owner. It creates a root-owned deployment wrapper and a restricted `neomarket-deploy` SSH account; it does not add the account to `docker`, install arbitrary sudo, replace Caddy/Nginx, or create application secrets.

## Evidence gaps

Firewall rules, effective SSH configuration, current container inventory, and existing root-owned data require the owner-run verification command. Until then the staging release is BLOCKED.

## Runtime update — 2026-10-20 11:10

The protected staging bootstrap and deployment path are now active. The legacy demo Nginx listener on `127.0.0.1:8080` was preserved; NeoMarket gateway uses `127.0.0.1:18080`. The fixed-SHA deployment for image `7c1951054cf3c4e69b4e1a38769c2ca640da2f89` completed migrations and smoke checks. All required containers reported healthy, and Caddy HTTPS probes reached the four staging virtual hosts. Browser trust of the Caddy internal CA, backup/restore and authenticated end-to-end evidence remain open.
