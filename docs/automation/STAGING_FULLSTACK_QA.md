# NeoMarket Fullstack Staging QA ? 2026-10-20

## Release status

**BLOCKED.** SSH access and the restricted staging runtime are present, and read-only endpoint probes pass for the public boundaries. The current `dae7914` runtime is healthy and the real Admin OIDC login endpoint now issues a 307 redirect to Keycloak with PKCE/state/nonce. Full release gates remain open because Keycloak MFA claims are not configured, authenticated Admin/visual QA, backup/restore, provider/DLQ recovery evidence, and three independent Playwright manifests are still missing.

The protected staging runtime was deliberately deployed to the pinned SHA below. No production deployment was performed.

## Scope and sources

- Repository instructions: `AGENTS.md`.
- Current production specifications: `docs/NeoMarket_Admin_Production_Spec_2026-10-16/` and `docs/NeoMarket_Seller_Production_Blueprint_2026-10-16/`.
- Staging manifests: `deploy/staging/`.
- Local branch: `staging`; local HEAD contains later documentation-only commits. Those commits are not deployed.
- The local worktree is dirty; the current deployed staging release is `dae79147dac0b4d86e4397981e86f7bec10d3faa` (see `evidence/staging/status-dae7914-20261020T143121Z.txt`).
- Requested `$neomarket-exhaustive-qa` skill was not present in the configured skill roots or repository skill directory.

## Latest OIDC staging verification

- CI and the restricted deployment completed for immutable SHA `dae79147dac0b4d86e4397981e86f7bec10d3faa`; all required services and workers report healthy.
- Server-side discovery and token metadata fetches use the private `keycloak:8080` service. The public issuer remains `https://keycloak.neomarket.test/realms/neomarket-staging` for browser redirects and issuer validation.
- `GET https://admin.neomarket.test/api/auth/login` returned `307 Temporary Redirect` with the expected authorization endpoint, `response_type=code`, PKCE `S256`, state, nonce, `prompt=login`, and `max_age=0`. Evidence: [`admin-oidc-private-keycloak-dae79147dac0b4d86e4397981e86f7bec10d3faa-20261020T143102Z.json`](evidence/staging/admin-oidc-private-keycloak-dae79147dac0b4d86e4397981e86f7bec10d3faa-20261020T143102Z.json).
- Fresh Chromium staging checks on the same SHA passed **75/75** across desktop, tablet and mobile: 72 anonymous protected-route/forged-cookie cases and 3 cross-origin CSRF cases. Evidence: [`admin-boundary-dae7914-20261020T144500Z.json`](evidence/staging/admin-boundary-dae7914-20261020T144500Z.json) and the persisted Playwright report.
- This is OIDC discovery/redirect evidence only. No staff credentials or MFA claims were used; authenticated Admin browser acceptance remains BLOCKED and fail-closed.

## Latest local release regression

- Commit `e0c8042` replaces the deleted legacy spec validator in `ci/verify.sh` and the production-gates workflow with a structural validator for the current 2026-10-16 Admin specification. The validator passes for both OpenAPI targets and all 202 acceptance rows.
- B2B: `285 passed, 38 skipped`; B2C unit gate: `154 passed, 10 deselected` (the PostgreSQL integration marker is run separately); Admin: `57 passed, 65 skipped`; shared/repository: `28 passed`.
- Ruff, `uv lock --check`, OpenAPI route comparison and staging Compose security checks pass. The PowerShell host cannot execute `ci/verify.sh` through its WSL `bash` shim because that shim is configured with a missing `C:\rtz\wsl\Ubuntu\ext4.vhdx`; the equivalent gate commands were run directly and passed.

## Stage 1 ? server audit

### Access and capacity

- SSH alias: `market-staging`, `ter0o@192.168.0.112:22`.
- Connection succeeded again at `2026-10-20T18:15:31+05:00`; read-only audit: [ssh-retry-audit-20261020T181531.txt](evidence/staging/ssh-retry-audit-20261020T181531.txt).
- Hostname: `dev`; Ubuntu `26.04.1 LTS`, kernel `7.0.0-38-generic`, x86_64.
- AMD Ryzen 5 3600, 6 cores / 12 threads.
- RAM: 15 GiB total, 13 GiB available; swap 4 GiB unused.
- Root filesystem `/dev/sdb2`: ext4, 468 GiB, 101 GiB used, 343 GiB free (23%).
- `/dev/sda1`: 931.5 GiB NTFS, not mounted in the inspected filesystem table.

### Docker and privilege boundary

- Docker Engine `29.9.1`; Compose `v5.6.0`; Docker and containerd services are active.
- `ter0o` is not in the `docker` group; `/var/run/docker.sock` is `root:docker` mode `0660`.
- Direct `docker ps/info/network` calls return `permission denied`.
- `sudo -n` requires interactive authentication.
- Root-only deployment wrapper: `/usr/local/sbin/neomarket-staging-deploy`.
- Read-only wrapper: `/usr/local/sbin/neomarket-staging-status`, but it cannot read `/etc/neomarket/staging.env` as `ter0o`; no secret was read.
- The SSH guard accepts only a validated SHA request or `neomarket-staging-status`; the protected SHA request was used for the staging redeploy recorded below.

### Fresh SSH retry

- A new `ssh -o BatchMode=yes market-staging` login succeeded as `ter0o` on host `dev`; direct read-only identity and hostname checks work.
- The status wrapper currently exits non-zero while trying to `stat /etc/neomarket/staging.env` because the file is root-only. This does not expose secrets and does not invalidate the previously captured healthy runtime status, but a root-owned wrapper fix is required before a new live container status capture can be made through this account.
- Public read-only probes with the staging host mapping returned Admin health `200`, Admin OIDC login `307` to Keycloak, and Keycloak discovery `200`.

### Network and proxy

- `enp4s0`: `192.168.0.112/24`.
- Public listeners: `22`, `80`, `443`; internal listeners: `127.0.0.1:18080`, `127.0.0.1:8080`, `127.0.0.1:2019`.
- Caddy uses its local CA and reverse proxies the four private staging hostnames to `127.0.0.1:18080`.
- The old demo Nginx remains on `127.0.0.1:8080`.
- UFW/nftables could not be checked without root (`Operation not permitted`).
- Fail2Ban is active.

## Runtime discovered on the host

The root-owned deployment layout is present under `/opt/neomarket-staging/compose` with compose, migration, smoke, and status scripts. `/opt/neomarket-staging/last-successful-sha` contains:

```text
d30c5d843f741213db7d11278bb528c586655b90
```

`/opt/neomarket-staging/.release.env` points to `ghcr.io/zein75/market` with the same SHA. The value is metadata only; container status cannot be read directly by `ter0o` because the environment file and Docker socket are protected.

## Read-only staging probes

All probes were run against the server through SSH with Caddy's internal TLS verification disabled only for this local probe (`curl -k`); this is not a browser QA result.

| Host | `/` | `/api/health` | Boundary result |
|---|---:|---:|---|
| `storefront.neomarket.test` | 200 | 200 | storefront responds |
| `seller.neomarket.test` | 200 | 200 | seller responds |
| `admin.neomarket.test` | 307 | 200 | redirects anonymous user to `/unauthorized` |
| `keycloak.neomarket.test` | 302 | n/a | redirects to Keycloak admin; realm discovery succeeds at `/realms/neomarket-staging/.well-known/openid-configuration` |

Port exposure is consistent with the checked-in staging policy: gateway is localhost-only and Caddy is the public boundary.

## Repository and CI checks

The checked-in static check passed:

```text
.venv\\Scripts\\python.exe ci/check_staging_config.py
Static staging Compose security: PASS
```

This proves only static Compose properties. It does not prove secrets, container health, migrations, TLS trust in browsers, or external integrations.

The latest successful image build for the current release was workflow run `39437627719` for SHA `d30c5d843f741213db7d11278bb528c586655b90`; static checks, PostgreSQL migration/concurrency tests, and all six image builds passed. The protected staging deployment completed through the root-owned wrapper.

## Stage 2–7 result

The protected runtime status and startup migrations are verified. The B2B suite completed with `285 passed, 38 skipped, 0 failed`; a fresh Chromium Seller fixture on the code-equivalent `20cd369` runtime authenticated and returned `200` on 11 protected routes with an HttpOnly session and no unexpected 5xx responses; ClamAV detected EICAR and accepted a clean sample; and bounded PostgreSQL and Redis stop/start drills returned readiness `503` during each dependency outage and `200` after recovery without deleting volumes. The current `d30c5d8` status and HTTPS probes are healthy. These checks do not prove the full release: Keycloak MFA/OIDC claims, authenticated Admin workflows, visual comparison, upload/quarantine end-to-end behavior, retry/DLQ/provider drills, off-host backup/restore and the three independent release-gate manifests remain open.

## Required next steps

1. Provide a controlled staging Admin test identity with a known temporary password and TOTP enrollment path, or an approved root-only fixture command. Do not place credentials in Git or chat.
2. Configure and document the Keycloak MFA/step-up policy. Discovery currently advertises only ACR `0` and `1`; no ACR `2`/`3` step-up is configured.
3. Run authenticated Admin BFF and browser workflows, including two-tab concurrency, UI/visual checks, and three independent manifests on this deployed SHA.
4. Run isolated backend flows for moderation, appeals, evidence scanning/quarantine, retry/DLQ, search/cache reconciliation, and offsite backup/restore.
5. Configure an approved external backup target and execute the restore runbook with measured RPO/RTO.
6. Fixture cleanup is verified on `ee079032`; continue using unique run IDs and always execute the protected destroy command after isolated Seller/B2B QA.
7. Keep unsupported external contracts fail-closed until their authoritative provider and approval policy are supplied.

## Evidence

- [raw.txt](evidence/staging-audit-2026-10-20/raw.txt)
- [raw-2.txt](evidence/staging-audit-2026-10-20/raw-2.txt)
- [raw-3.txt](evidence/staging-audit-2026-10-20/raw-3.txt)
- [raw-4.txt](evidence/staging-audit-2026-10-20/raw-4.txt)
- [raw-5.txt](evidence/staging-audit-2026-10-20/raw-5.txt)
- [raw-6.txt](evidence/staging-audit-2026-10-20/raw-6.txt)
- [raw-7.txt](evidence/staging-audit-2026-10-20/raw-7.txt)
- [raw-8.txt](evidence/staging-audit-2026-10-20/raw-8.txt)
- [raw-9.txt](evidence/staging-audit-2026-10-20/raw-9.txt)
- [status-20261020T131059Z.txt](evidence/staging/status-20261020T131059Z.txt)
- [gateway-routes-20261020T131059Z.txt](evidence/staging/gateway-routes-20261020T131059Z.txt)
- [admin-anonymous-boundary-ee079-20261020T181628.json](evidence/staging/admin-anonymous-boundary-ee079-20261020T181628.json) (72/72, current deployed SHA)
- [admin-csrf-boundary-ee079-20261020T181628.json](evidence/staging/admin-csrf-boundary-ee079-20261020T181628.json) (3/3, current deployed SHA)
- [gateway-retry-20261020T181841.txt](evidence/staging/gateway-retry-20261020T181841.txt)
- [status-retry-20261020T1819.txt](evidence/staging/status-retry-20261020T1819.txt)
- [keycloak-oidc-discovery-20261020T131059Z-summary.json](evidence/staging/keycloak-oidc-discovery-20261020T131059Z-summary.json)
- [admin-regression-5eb9fc6-2026-10-20/REPORT.md](evidence/admin-regression-5eb9fc6-2026-10-20/REPORT.md)
- [admin-regression-6ec5ab6-2026-10-20/REPORT.md](evidence/admin-regression-6ec5ab6-2026-10-20/REPORT.md)
- [qa-fixture-fk-failure-3a1e7e9.txt](evidence/staging/qa-fixture-fk-failure-3a1e7e9.txt)
- [qa-fixture-create-destroy-c1ba25c.txt](evidence/staging/qa-fixture-create-destroy-c1ba25c.txt)
- [status-ee07903-20261020.txt](evidence/staging/status-ee07903-20261020.txt)
- [status-872b0a1-20261020.txt](evidence/staging/status-872b0a1-20261020.txt) (current live runtime)
- [status-b7e07e7-20261020.txt](evidence/staging/status-b7e07e7-20261020.txt) (current live runtime)
- [https-health-b7e07e7-20261020.txt](evidence/staging/https-health-b7e07e7-20261020.txt)
- [status-20cd369-20261020.txt](evidence/staging/status-20cd369-20261020.txt) (current live runtime)
- [https-health-20cd369-20261020.txt](evidence/staging/https-health-20cd369-20261020.txt)
- [status-d30c5d8-20261020.txt](evidence/staging/status-d30c5d8-20261020.txt) (current live runtime)
- [https-health-d30c5d8-20261020.txt](evidence/staging/https-health-d30c5d8-20261020.txt)
- [b2b-authenticated-routes-20cd369-20261020.json](evidence/staging/b2b-authenticated-routes-20cd369-20261020.json)
- [qa-fixture-create-destroy-20cd369-20261020.json](evidence/staging/qa-fixture-create-destroy-20cd369-20261020.json)
- [smoke-ee07903-20261020.txt](evidence/staging/smoke-ee07903-20261020.txt)
- [clamav-ee079032-20261020.json](evidence/staging/clamav-ee079032-20261020.json)
- [qa-fixture-create-destroy-ee07903-20261020.json](evidence/staging/qa-fixture-create-destroy-ee07903-20261020.json)
- [b2b-regression-ee07903-20261020.txt](evidence/staging/b2b-regression-ee07903-20261020.txt)
- [b2b-authenticated-routes-ee07903-20261020.json](evidence/staging/b2b-authenticated-routes-ee07903-20261020.json)
- [db-outage-drill-ee07903-20261020.json](evidence/staging/db-outage-drill-ee07903-20261020.json)
- [redis-outage-drill-ee07903-20261020.json](evidence/staging/redis-outage-drill-ee07903-20261020.json)
- [release-check-20261020T1311Z.json](evidence/staging/release-check-20261020T1311Z.json)
- [metadata.json](evidence/staging-audit-2026-10-20/metadata.json)

