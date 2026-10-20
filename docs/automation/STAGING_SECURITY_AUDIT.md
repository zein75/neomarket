# NeoMarket staging security audit

**Status:** `BLOCKED / partial static review`.

## Completed

- Static staging Compose security check passes.
- No application service except the loopback gateway publishes a host port.
- Admin development authentication is disabled in the staging manifest.
- API and frontend images are SHA-tagged.
- New bootstrap does not grant Docker socket access or arbitrary sudo.
- ClamAV is internal-only and media data uses a persistent private volume.

## Not yet testable

Runtime authentication, OIDC/JWKS, MFA/step-up, RBAC/IDOR, CSRF, cookie flags, CORS/CSP, upload scanning, rate limits, audit trails, container runtime privileges, firewall, TLS, and secret exposure require a deployed release and privileged owner verification. No security gate is PASS based on documentation alone.

## Runtime update — 2026-10-20

The Compose security gate, fixed-SHA deployment, internal-only service ports, Caddy ingress, API smoke checks and negative internal-route checks passed on the live staging runtime. Full authentication, OIDC/MFA, RBAC/IDOR, CSRF, upload scanning, firewall and browser security evidence remains open.
