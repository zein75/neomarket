# Runtime addendum — 2026-10-20 11:10

The earlier audit below is historical. The current staging runtime is deployed and verified as follows:

- Image release: `7c1951054cf3c4e69b4e1a38769c2ca640da2f89`.
- Deployment/config commit: `772ace6`.
- Protected deployment ended with `SMOKE PASS` and `DEPLOY_SUCCESS`.
- B2C, B2B, Admin, workers, PostgreSQL, Redis, Keycloak, ClamAV, Mailpit, all three frontends and gateway are healthy.
- Gateway is `127.0.0.1:18080`; legacy demo Nginx remains on `127.0.0.1:8080`.
- Caddy `--resolve` probes: Storefront 200, Seller 200, Admin 307 login boundary, Keycloak 302.
- Browser QA is still BLOCKED because the current browser environment does not trust Caddy's internal CA. No TLS verification bypass was used for a browser result.
- Backup/restore, authenticated OIDC/MFA, full Seller/Admin/B2C journeys, visual regression and three independent manifests remain NOT RUN.
# NeoMarket Fullstack Staging QA - 2026-10-20

## Final status

**BLOCKED - S0 audit and restricted bootstrap completed; application deployment is blocked by missing protected staging secrets and provider/TLS configuration.**

The server is reachable over SSH, but the observed host is `dev` with demo services. The NeoMarket checkout is not available to the requested user, Docker access is closed to the QA/deployment user, and firewall/effective SSH policy cannot be verified without an approved privileged mechanism. No server changes, deployment, migrations, or production actions were performed.

## Sources and project version

- `AGENTS.md` at repository root.
- Current Admin specification: `docs/NeoMarket_Admin_Production_Spec_2026-10-16/`.
- Seller blueprint: `docs/NeoMarket_Seller_Production_Blueprint_2026-10-16/`.
- Staging config: `deploy/staging/`, `deploy/staging/docker-compose.staging.yml`, `deploy/staging/nginx.conf`.
- Local branch: `staging`.
- Local HEAD: `b101458e41d028bf22a7790652b24d54981f7241`.
- Local worktree is not a clean release snapshot; this SHA is not a verified staging release SHA.
- Requested `$neomarket-exhaustive-qa` skill was not found in configured skill roots or repository `.agents/skills`.
- Restricted deployment bootstrap is installed from `deploy/staging/bootstrap/`; runtime access remains through the root-owned wrapper because `ter0o` cannot access Docker or non-interactive sudo.
- Owner bootstrap is now installed on `market-staging`; a forced SHA request reached the root wrapper and was rejected before Docker/data changes because `/etc/neomarket/staging.env` is absent.

## Stage 1 - read-only server audit

### Access

- SSH alias: `market-staging`.
- User: `ter0o`.
- Address: `192.168.0.112:22`.
- Connection succeeded: `uid=1000(ter0o)`, host `dev`, timestamp `2026-10-20T12:50:38+05:00`.
- User is also in `sudo` and `lxd` groups; no escalation/LXD access was used.
- Server account `marketqa` (UID 1001) exists, but the local `market-qa` alias has no usable key.

### OS and capacity

- Ubuntu `26.04.1 LTS`, kernel `7.0.0-38-generic`, x86_64.
- AMD Ryzen 5 3600: 6 cores / 12 threads.
- RAM: 15 GiB total, 13 GiB available.
- Swap: 4 GiB, unused.
- Root `/dev/sdb2`: ext4, 468 GiB, 101 GiB used, 343 GiB free (23%).
- Additional `/dev/sda1`: 931.5 GiB NTFS, not mounted in the inspected filesystem table.

### Docker and privileges

- Docker Engine `29.9.1` and Compose `v5.6.0` installed.
- `docker.service` and `containerd.service` active/running.
- `ter0o` is not in the `docker` group.
- `/var/run/docker.sock`: `root:docker`, mode `0660`.
- `docker ps`, `docker info`, and `docker network ls` return `permission denied` for `ter0o`.
- `sudo -n` is unavailable; sudo requires interactive authentication.
- Root or Docker socket access was not granted to the QA user.

### Network and existing services

- `enp4s0`: `192.168.0.112/24`.
- TCP listeners: `22`, `80`, loopback `631`, `8080`, and `2019`.
- `80/tcp`: Caddy serving the default static page.
- `8080/tcp`: Nginx demo bound to `127.0.0.1`.
- `2019/tcp`: HTTP 404; service identity not established.
- No public PostgreSQL, Redis, B2C, B2B, or Admin ports were observed in the host socket table.

### Staging filesystem

- `/srv/staging/projects/demo/compose.yaml` is the only visible Compose project under `/srv/staging/projects`.
- The demo Compose project runs only `nginx:stable-alpine` on `127.0.0.1:8080`.
- `/srv/staging/monitoring`, `/srv/staging/proxy`, and `/srv/staging/backups` exist but contain no visible files at the inspected depth.
- `/srv/neomarket` exists but is inaccessible to `ter0o` (`Permission denied`).
- `/etc/caddy/Caddyfile` contains only the default static `:80` site; NeoMarket reverse proxy and HTTPS virtual hosts are absent.

### Firewall and SSH

- UFW/nftables could not be checked: root is required (`Operation not permitted`). This is an evidence gap, not PASS.
- SSH service is active.
- `systemctl is-enabled ssh` reports `disabled`; `sshd -T` could not read host keys as the unprivileged user. Effective SSH policy remains unverified.
- Fail2Ban service is active.

## Repository staging configuration check

Command:

```text
.venv\Scripts\python.exe ci/check_staging_config.py
```

Result:

```text
Static staging Compose security: PASS (including internal-only ClamAV and private media volume checks).
```

This is a static repository check only. It does not prove effective Docker Compose, secrets, image pulls, hostname, firewall, or a running staging stack.

Checked static properties include:

- `ADMIN_ALLOW_DEV_AUTH=false` in staging;
- no host ports on internal services;
- gateway only on `127.0.0.1:8080`;
- internal backend network;
- isolated Admin DB/network;
- dedicated worker;
- immutable `${RELEASE_SHA}` images;
- rejection of unknown gateway hosts.

## Stage 1 conclusion

The server is **not verified as a NeoMarket staging target**. There is no accessible NeoMarket checkout/Compose deployment and no evidence of Keycloak, private storage, antivirus, backup, B2C, B2B, Admin, or frontend services running there.

Deployment must not proceed until the target path and approved deployment mechanism are identified. Deploying now could affect the existing Caddy/Nginx/demo services without producing valid staging evidence.

## Required to continue

1. Provide an approved restricted deployment mechanism without adding `ter0o` to `docker` or exposing the Docker socket/root.
2. Identify the actual staging checkout/release directory and owner, or run the approved CI deployment.
3. Provide an approved read-only privileged audit path for firewall and effective SSH policy.
4. Confirm staging hostname/DNS/HTTPS and gateway ownership.
5. Confirm Keycloak realm/client/MFA claims, private object storage, antivirus/quarantine, backup target, and secret injection source.
6. Then run migrations, health checks, browser QA, and three independent Playwright manifests on one immutable SHA.

## Raw evidence

- [raw.txt](evidence/staging-audit-2026-10-20/raw.txt)
- [raw-2.txt](evidence/staging-audit-2026-10-20/raw-2.txt)
- [raw-3.txt](evidence/staging-audit-2026-10-20/raw-3.txt)
- [raw-4.txt](evidence/staging-audit-2026-10-20/raw-4.txt)
- [raw-5.txt](evidence/staging-audit-2026-10-20/raw-5.txt)

