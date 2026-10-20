# NeoMarket staging security audit

**Status:** `BLOCKED / partial static review`.

## Completed

Current protected runtime evidence is pinned to application image SHA `b0fd2323d8fa5c6df166018f0e5f7c0cfdb4c565`; the historical runtime update below is retained for audit provenance.

- Static staging Compose security check passes.
- No application service except the loopback gateway publishes a host port.
- Admin development authentication is disabled in the staging manifest.
- API and frontend images are SHA-tagged.
- New bootstrap does not grant Docker socket access or arbitrary sudo.
- ClamAV has no host port, accepts scanner traffic only on the private backend network, and uses a separate egress-only updater network; media data uses a persistent private volume.

## Runtime evidence

- The deployed fixed-SHA runtime is reachable only through the Caddy staging ingress; application services remain internal and the gateway is loopback-only.
- Anonymous Admin protected-page and forged-cookie boundary checks passed 72/72 across desktop, tablet and mobile contexts.
- The staging CSRF boundary reached the application gate and returned `403 CSRF_VALIDATION_FAILED` with `Cache-Control: no-store`.
- Keycloak discovery is available, but the realm advertises only ACR `0` and `1`; no ACR `2`/`3` step-up policy is configured.

Authenticated OIDC/MFA, RBAC/IDOR, upload scanning, rate limits, audit trails, container runtime privileges, firewall owner verification, backup/restore and authenticated browser evidence remain open. No release gate is marked PASS from documentation alone.

## Runtime update — 2026-10-20

The Compose security gate, fixed-SHA deployment `ee079032cfd234ddd3232c4dfc74fc84b1a5bc22`, internal-only service ports, Caddy ingress, API smoke checks and negative internal-route checks passed on the live staging runtime. The real ClamAV probe detected EICAR and accepted a clean sample; FreshClam signature refresh is still blocked by upstream HTTP 403/cooldown. Controlled PostgreSQL and Redis stop/start drills returned B2B readiness 503 during each outage and 200 after recovery without deleting volumes. Current evidence: `docs/automation/evidence/staging/status-ee07903-20261020.txt`, `smoke-ee07903-20261020.txt`, `clamav-ee079032-20261020.json`, `db-outage-drill-ee07903-20261020.json`, and `redis-outage-drill-ee07903-20261020.json`. Authenticated OIDC/MFA, RBAC/IDOR, full upload/quarantine workflow, alert verification, firewall owner verification and authenticated browser security evidence remain open.
