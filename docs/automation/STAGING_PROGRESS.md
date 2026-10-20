# Staging progress

**Latest verification:** 2026-10-20 (local regression and frontend release checks)

The staging refresh helper was hardened in `bcdcddb`: when run from `/tmp/neomarket-src/deploy/staging/bootstrap/refresh_root_files.sh`, it reads the checked-out manifests directly and updates the root-owned deployment wrapper. The host applied the refresh and a fixed-SHA redeploy on 2026-10-20.

Independent local checks on the current checkout:

- B2B: `285 passed, 38 skipped`.
- B2C (excluding opt-in PostgreSQL integration): `154 passed, 10 deselected`.
- Admin: `56 passed, 65 skipped`.
- Shared/target tests: `27 passed`.
- Ruff, OpenAPI target validation, Compose security, and Python compilation: PASS.
- Frontend typecheck and production build for Storefront, Seller, Admin, and shared packages: PASS.
- GitHub Actions run `39417180391` for `f8dfbf1`: verify, PostgreSQL integration, and all six immutable image builds PASS; hosted staging deploy was skipped because `192.168.0.112` is private.

**Updated:** 2026-10-20 (runtime verification after deployment)
| Phase | Status | Evidence |
|---|---|---|
| S0 host audit | DONE | `STAGING_INFRA_AUDIT.md` and captured server audit |
| S1 restricted deployment | DONE | fixed-SHA wrapper, forced SSH command, root-only Docker credentials |
| S2 filesystem/secrets | DONE | root-owned `/etc/neomarket/staging.env`, persistent volumes, no secret values in Git |
| S3 Compose runtime | PASS | deployment `c073e744…` completed; all required services, both workers and gateway healthy |
| S4 ingress/HTTPS | PARTIAL | Caddy internal TLS works; fixed-SHA redeploy recreated the gateway and live host probes now return the expected Storefront/Seller/Admin health payloads. CA/browser trust is still not installed |
| S5 migrations/integration | PASS for startup | B2B, B2C and Admin migrations completed; PostgreSQL/Redis healthy |
| S6 Keycloak/OIDC/MFA | PARTIAL | Keycloak realm imported and healthy; real browser OIDC/MFA evidence not run |
| S7 media/antivirus | PASS for startup | ClamAV healthy and B2B depends on it; full upload/quarantine evidence not run |
| S8 workers/events | PASS for startup | taxonomy/recovery/admin workers running; retry/DLQ scenario evidence not run |
| S9 CI/CD | PARTIAL | CI verify and six image builds pass; hosted runner cannot reach private staging, so deployment is executed through the restricted local SSH path |
| S10 browser QA | BLOCKED | Caddy CA is untrusted in the current browser environment; no authenticated manifests |
| S13 backup/restore | NOT RUN | external backup target and restore drill are not configured |
| S14 security audit | PARTIAL | static Compose gates and ingress smoke passed; full runtime audit remains |

**Current release status: BLOCKED.** Production readiness is not asserted while browser, backup/restore, authenticated QA, visual, and full security evidence are missing.

**Runtime evidence (2026-10-20T11:50:01Z):** deployment `c073e7446d6d639f73644a1b68d2110ed234b325` completed through the restricted `neomarket-deploy` SSH command. Gateway probes are recorded in `evidence/staging/gateway-routes-20261020T115001Z.txt`; the status capture is `evidence/staging/status-20261020T115001Z.txt`. All required containers reported `running` and `healthy`; the deployment smoke check returned `SMOKE PASS`.

The public Keycloak discovery document also resolves through Caddy with the configured staging issuer, JWKS URL and PKCE `S256` support; the response is recorded in `evidence/staging/keycloak-oidc-discovery-20261020T1152Z.json`. This is provider discovery evidence only and does not promote browser MFA/OIDC acceptance.

The acceptance checker still returns `BLOCKED` (`202` required cases, `0` of `3` authenticated manifests):
`python docs/NeoMarket_Admin_Production_Spec_2026-10-16/qa/check_release.py --matrix docs/NeoMarket_Admin_Production_Spec_2026-10-16/qa/ACCEPTANCE_MATRIX.csv --runs-dir docs/automation/seller_runs`.
