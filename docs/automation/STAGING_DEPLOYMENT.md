# NeoMarket staging deployment

**Status:** `PARTIAL` — protected bootstrap and restricted deployment are installed; runtime release is blocked by two fixed compose/image defects awaiting root-owned compose refresh.

The deployment workflow now requests a fixed SHA through the root-owned `neomarket-staging-deploy` wrapper. It no longer rsyncs executable Compose or shell files as the deployment user. The wrapper is installed by `deploy/staging/bootstrap/bootstrap.sh` and records `/var/log/neomarket-staging/deploy.log` plus `/opt/neomarket-staging/last-successful-sha`.

Evidence from `192.168.0.112`:

- `1ceba9fbce7105866f48536a09d087c80c3e4f47` was pulled and migrations completed.
- Admin, B2B, B2C and their workers reached healthy/readiness states.
- Keycloak PostgreSQL and Keycloak reached healthy state.
- Deployment stopped at the real `clamd` health gate; Mailpit also restarted. Existing frontend images used an unavailable `wget` healthcheck.
- `40ffdc140006174ed504c96dc61a15a444e1ade5` removes the invalid Mailpit TLS path and read-only ClamAV root filesystem and expands diagnostics.
- `e4249b7cbb6341eb70577657a925606a2234d12f` replaces frontend `wget` healthchecks with Node's built-in `fetch`.

CI runs `39405875211` and `39406495189` passed verify, integration and image builds. Run `39406685722` is building the frontend healthcheck fix. A root owner must refresh the immutable files under `/opt/neomarket-staging/compose` before requesting `e4249b7`; application data and volumes do not need removal.
