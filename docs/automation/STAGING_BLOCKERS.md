# NeoMarket staging blockers

1. **Root refresh for the compose-path fix is pending (P0):** the owner has applied the first root refresh, generated provider values and GHCR pull credentials, and image pulls now succeed. The next deployment exposed a path mismatch between the root wrapper (`/opt/neomarket-staging/compose`) and the helper scripts. Commit `617a117` fixes that mismatch; the owner must rerun the restricted bootstrap once to install the corrected root-owned scripts.
3. **Keycloak and TLS absent (P0 Admin):** runtime deployment has not completed, so no trusted CA, or approved redirect/issuer host has been verified.
4. **Object storage contract absent (P1 media):** the current implementation is a private local media volume; S3/MinIO must not be claimed until the approved storage contract is implemented and tested.
5. **Browser QA absent (P0 release):** no authenticated staging Playwright manifests or visual evidence exist.
6. **Backup/restore absent (P1 operations):** external backup target and a restore drill are not configured.

These are evidence-based blockers, not waived requirements.
