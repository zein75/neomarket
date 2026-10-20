# Staging progress

**Latest verification:** 2026-10-20 (local regression and frontend release checks)

The staging refresh helper was hardened in `bcdcddb`: when run from `/tmp/neomarket-src/deploy/staging/bootstrap/refresh_root_files.sh`, it reads the checked-out manifests directly and updates the root-owned deployment wrapper. The host has not yet applied this commit; live route probes therefore still show `STAGING-GW-001`.

Independent local checks on the current checkout:

- B2B: `285 passed, 38 skipped`.
- B2C (excluding opt-in PostgreSQL integration): `154 passed, 10 deselected`.
- Admin: `56 passed, 65 skipped`.
- Shared/target tests: `27 passed`.
- Ruff, OpenAPI target validation, Compose security, and Python compilation: PASS.
- Frontend typecheck and production build for Storefront, Seller, Admin, and shared packages: PASS.

**Updated:** 2026-10-20 (runtime verification after deployment)
| Phase | Status | Evidence |
|---|---|---|
| S0 host audit | DONE | `STAGING_INFRA_AUDIT.md` and captured server audit |
| S1 restricted deployment | DONE | fixed-SHA wrapper, forced SSH command, root-only Docker credentials |
| S2 filesystem/secrets | DONE | root-owned `/etc/neomarket/staging.env`, persistent volumes, no secret values in Git |
| S3 Compose runtime | PASS | deployment `c073e744…` completed; all required services, both workers and gateway healthy |
| S4 ingress/HTTPS | BLOCKED | Caddy internal TLS works, but `STAGING-GW-001` swaps Storefront/Admin host routing until root gateway refresh is applied; CA/browser trust also not installed |
| S5 migrations/integration | PASS for startup | B2B, B2C and Admin migrations completed; PostgreSQL/Redis healthy |
| S6 Keycloak/OIDC/MFA | PARTIAL | Keycloak realm imported and healthy; real browser OIDC/MFA evidence not run |
| S7 media/antivirus | PASS for startup | ClamAV healthy and B2B depends on it; full upload/quarantine evidence not run |
| S8 workers/events | PASS for startup | taxonomy/recovery/admin workers running; retry/DLQ scenario evidence not run |
| S9 CI/CD | PARTIAL | CI verify and six image builds pass; hosted runner cannot reach private staging, so deployment is executed through the restricted local SSH path |
| S10 browser QA | BLOCKED | Caddy CA is untrusted in the current browser environment; no authenticated manifests |
| S13 backup/restore | NOT RUN | external backup target and restore drill are not configured |
| S14 security audit | PARTIAL | static Compose gates and ingress smoke passed; full runtime audit remains |

**Current release status: BLOCKED.** Production readiness is not asserted while browser, backup/restore, authenticated QA, visual, and full security evidence are missing.
