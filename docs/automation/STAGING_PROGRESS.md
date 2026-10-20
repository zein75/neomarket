# Staging progress

### Current staging release `0fcb935` — 2026-10-20

- GitHub Actions run `39439533285` passed static checks, PostgreSQL migration/concurrency checks and all six immutable image builds. The protected staging deployment completed on `0fcb935bfd14eba6eaa197898bf865e21eddfbd4`; the current status capture reports all application services, workers, gateway and Keycloak healthy: `docs/automation/evidence/staging/status-0fcb935-20261020.txt`.
- A real Chromium Seller keyboard sweep used a disposable staging fixture and the trusted Caddy CA at 1440x1100. Eight authenticated routes and 147 visible controls were traversed with zero invalid focus states, zero page errors and zero unexpected 5xx responses: `docs/automation/evidence/staging/seller-focus-0fcb935-20261020-tls.json`.
- This closes the observed missing focus ring on the two session controls in source commit `0fcb935`; UI-06 remains PARTIAL where the acceptance matrix requires manual screen-reader/modal review. Automated axe remains clean, while UI-07 manual assistive-technology evidence is still open.

**Latest verification:** 2026-10-20 (local regression and frontend release checks)

### Current live runtime `dae7914` — OIDC discovery and redirect verification

- Protected staging deployment completed on immutable SHA `dae79147dac0b4d86e4397981e86f7bec10d3faa`; all required services, workers, gateway and Keycloak are healthy. Evidence: `evidence/staging/status-dae7914-20261020T143121Z.txt`.
- Admin `GET /api/auth/login` now returns `307 Temporary Redirect` to the real Keycloak authorization endpoint with PKCE `S256`, state, nonce, `prompt=login`, and `max_age=0`. Server-side discovery uses private `keycloak:8080`; no public-DNS hairpin is required. Evidence: `evidence/staging/admin-oidc-private-keycloak-dae79147dac0b4d86e4397981e86f7bec10d3faa-20261020T143102Z.json`.
- MFA/step-up claims remain `не настроено`; no credentials or MFA codes were used. Authenticated Admin browser scenarios and the three independent manifests remain BLOCKED.

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
| S3 Compose runtime | PASS | deployment `fbbd473729746786?` completed; all required services, both workers and gateway healthy |
| S4 ingress/HTTPS | PARTIAL | Caddy internal TLS works; fixed-SHA redeploy recreated the gateway and live host probes return the expected Storefront/Seller/Admin health payloads. The current Playwright Chromium profile trusts the Caddy CA; authenticated browser evidence remains open |
| S5 migrations/integration | PASS for startup | B2B, B2C and Admin migrations completed; PostgreSQL/Redis healthy |
| S6 Keycloak/OIDC/MFA | PARTIAL | Keycloak realm imported and healthy; real browser OIDC/MFA evidence not run |
| S7 media/antivirus | PASS for startup | ClamAV healthy and B2B depends on it; full upload/quarantine evidence not run |
| S8 workers/events | PASS for startup | taxonomy/recovery/admin workers running; retry/DLQ scenario evidence not run |
| S9 CI/CD | PARTIAL | CI verify and six image builds pass; hosted runner cannot reach private staging, so deployment is executed through the restricted local SSH path |
| S10 browser QA | PARTIAL | Local Playwright now trusts the Caddy CA and resolves all staging hosts via Chromium host rules; 72 anonymous Admin boundary checks passed across desktop/tablet/mobile. Authenticated OIDC/MFA, Seller flows, visual baselines and the three release manifests remain outstanding |
| S13 backup/restore | NOT RUN | external backup target and restore drill are not configured |
| S14 security audit | PARTIAL | static Compose gates and ingress smoke passed; full runtime audit remains |

**Current release status: BLOCKED.** Production readiness is not asserted while browser, backup/restore, authenticated QA, visual, and full security evidence are missing.

### ClamAV updater investigation вЂ” 2026-10-20 18:55 local

- Compose release `cba15c1aa57641677dc57d1692da8bc38d5f8ac5` adds explicit DNS servers only to the private ClamAV container; static Compose security remains PASS and the full stack redeployed healthy.
- Runtime logs still report `Could not resolve hostname database.clamav.net` and `Update failed for database: daily`. The scanner process itself is healthy, but signature freshness is unavailable on this staging network. Media storage/antivirus remains PARTIAL and no false PASS is recorded.

### CSP font asset verification вЂ” 2026-10-20 18:48 local

- Release `82e12533be6e06b24a08f9ab2febc13e4589505d` passed CI, all six image builds, migration checks, and restricted staging deployment with `SMOKE PASS`.
- The enforced CSP now permits the Google font stylesheet/font origins already referenced by the three frontend shells. Real Chromium checks against Storefront, Seller and Admin returned HTTP 200, no CSP/font console violations, and no page errors. Evidence: `docs/automation/evidence/staging/csp-fonts-82e1253-20261020.json`.
- This closes the observed staging font CSP defect; it does not change the mandatory authenticated, visual, backup/restore or commercial release gates.

The release checker was rerun on `cba15c1`; it remains `BLOCKED` because the required three independent manifests are absent (`202` cases, `0/3` manifests). Evidence: `docs/automation/evidence/staging/release-check-cba15c1-20261020.json`.

Authenticated Seller state matrix on `cba15c1` covered 15 routes with HTTP 200 and no page errors. Truthful empty/unavailable states were observed for orders, product creation, onboarding, returns and finance; the finance `501 FEATURE_NOT_CONFIGURED` responses are intentional fail-closed behavior. Evidence: `docs/automation/evidence/staging/seller-state-matrix-cba15c1-20261020.json`. Fixture cleanup returned `deleted=true`.

**Runtime evidence (2026-10-20T11:50:01Z):** deployment `c073e7446d6d639f73644a1b68d2110ed234b325` completed through the restricted `neomarket-deploy` SSH command. Gateway probes are recorded in `evidence/staging/gateway-routes-20261020T115001Z.txt`; the status capture is `evidence/staging/status-20261020T115001Z.txt`. All required containers reported `running` and `healthy`; the deployment smoke check returned `SMOKE PASS`.

The public Keycloak discovery document also resolves through Caddy with the configured staging issuer, JWKS URL and PKCE `S256` support; the response is recorded in `evidence/staging/keycloak-oidc-discovery-20261020T1152Z.json`. This is provider discovery evidence only and does not promote browser MFA/OIDC acceptance.

The acceptance checker still returns `BLOCKED` (`202` required cases, `0` of `3` authenticated manifests):
`python docs/NeoMarket_Admin_Production_Spec_2026-10-16/qa/check_release.py --matrix docs/NeoMarket_Admin_Production_Spec_2026-10-16/qa/ACCEPTANCE_MATRIX.csv --runs-dir docs/automation/seller_runs`.

**Browser evidence (2026-10-20T11:56Z):** `admin-auth-boundary.spec.ts` ran against the real staging Admin host with Chromium host rules and the Caddy CA trusted in the current user store. All 72 anonymous protected-page/forged-cookie checks passed across desktop, tablet and mobile; report: `evidence/staging/admin-anonymous-boundary-20261020.json`. The separate APIRequestContext check was not promoted because Playwright's request client does not consume Chromium host rules and the local DNS names are intentionally private.

An additional real-browser smoke covered 24 public Storefront, Seller and Admin entrypoints across desktop, tablet and mobile; every response was HTTP 200 with a visible `<main>`. Report: `evidence/staging/public-browser-20261020.json`.

### Latest protected status and Admin boundary run РІР‚вЂќ 2026-10-20 17:15 local

- The forced-command CI deploy key first captured status on SHA `c073e7446d6d639f73644a1b68d2110ed234b325`; this is historical evidence only. The current protected deployment is SHA `3a1e7e9505fc76716322aa2ea9d97a4eff30672f`, with current status in `docs/automation/evidence/staging/status-20261020T1721Z.txt`.
- A fresh Chromium Playwright run against real `admin.neomarket.test` passed 72 anonymous protected-page and forged-cookie checks across desktop/tablet/mobile with the trusted Caddy local CA. This does not satisfy authenticated Admin acceptance or release manifests.
- Keycloak discovery on the protected staging host reports `acr_values_supported=[0,1]`; ACR 2/3 step-up is not configured. AMR scope support alone is not authenticated MFA evidence. Evidence: `docs/automation/evidence/staging/keycloak-oidc-discovery-20261020T1718Z-summary.json`.

### Immutable redeploy and repeat boundary ? 2026-10-20 17:22 local

- CI run `39421153548` completed successfully for SHA `3a1e7e9505fc76716322aa2ea9d97a4eff30672f`; all six images built and PostgreSQL migration/concurrency checks passed.
- The protected forced-command deployment completed and `last-successful-sha` is `3a1e7e9505fc76716322aa2ea9d97a4eff30672f`. All services became healthy after warm-up. Evidence: `docs/automation/evidence/staging/status-20261020T1721Z.txt`.
- Repeated Admin anonymous boundary: 72/72 passed across desktop/tablet/mobile with trusted Caddy CA. Evidence: `docs/automation/evidence/staging/admin-anonymous-boundary-3a1e7e9.json`.
- Repeated Caddy host and anonymous Admin API probes returned expected Storefront/Seller/Admin/Keycloak boundaries and `401 ADMIN_SESSION_REQUIRED` on protected Admin endpoints. Evidence: `docs/automation/evidence/staging/gateway-routes-20261020T1722Z.txt`.
- Staging CSRF browser probe initially exposed a test-fixture issue: `SameSite=Strict` cookies are correctly withheld on the cross-site form, so the request stopped at 401 before CSRF. The test now uses production `__Host-` cookie names with secure `SameSite=None` synthetic cookies only for this negative boundary; the real staging probe passes HTTP 403 `CSRF_VALIDATION_FAILED` with `no-store`. Evidence: `docs/automation/evidence/staging/admin-csrf-boundary-3a1e7e9/REPORT.md`.
- The protected `neomarket-staging-qa-fixture` probe exposed deployment drift: the root-installed fixture copy is stale. The first create returned ephemeral fixture data, while the destroy request followed the stale create path and failed on a `products.seller_id` NOT NULL violation. Cleanup is therefore unconfirmed and must be handled by the root owner after refreshing `/opt/neomarket-staging/qa/b2b_fixture.py` from the checked-out source. Evidence: `docs/automation/evidence/staging/qa-fixture-fk-failure-3a1e7e9.txt`.
- Fresh release checker result: 202 required cases, 170 PASS, 32 NOT_RUN, and 0/3 independent manifests; result `BLOCKED`. Evidence: `docs/automation/evidence/staging/release-check-20261020T1813Z.json`.

### Latest redeploy and repeat boundary ? 2026-10-20 18:01 local

- CI run `39422677045` completed successfully for SHA `fbbd47372974678638ed0cc48967fa73e4a3d3a8`; all six images built and migration/concurrency checks passed.
- Protected staging deployment completed with `SMOKE PASS` and all required services healthy on SHA `fbbd47372974678638ed0cc48967fa73e4a3d3a8`. Evidence: `docs/automation/evidence/staging/status-20261020T1800Z.txt`.
- Admin anonymous boundary passed 72/72 across desktop/tablet/mobile, and CSRF boundary passed 3/3. Evidence: `admin-anonymous-boundary-fbbd473.json`, `admin-csrf-boundary-fbbd473.json`.
- Gateway probes returned Storefront/Seller 200, Admin anonymous redirect 307, Keycloak 302, Admin health 200 and protected moderation 401. Evidence: `docs/automation/evidence/staging/gateway-routes-20261020T1801Z.txt`.

### Authenticated Seller follow-up вЂ” 2026-10-20

- Release `fbbd47372974678638ed0cc48967fa73e4a3d3a8` passed verify/integration and all six immutable image builds, then completed the restricted staging deployment with healthy services and `SMOKE PASS`.
- Fixed Seller middleware session validation to call the internal `NEOMARKET_B2B_URL/auth/me` service route instead of recursively calling the public BFF origin from inside the frontend container. This removed false login redirects on private Seller pages.
- Fixed the staging QA fixture email suffix from `.test` to `.internal`; the former was rejected by the same `EmailStr` validator used by the live team response and caused a real `/team/members` 500.
- Authenticated Chromium sweep on the real staging host: 11/11 protected Seller routes stayed on the requested URL with HTTP 200; runtime error sweep was empty; axe violations were empty on eight core routes. Evidence: `docs/automation/evidence/staging/b2b-authenticated-routes-fbbd473-20261020.json` and `docs/automation/evidence/staging/b2b-authenticated-runtime-fbbd473-20261020.json`.
- ADR-001 was added to the repository but remains `PROPOSED / LEGAL_AND_PSP_REVIEW_REQUIRED`; returns, restock, PSP, payout and fiscal flows remain fail-closed and release-blocking until the required approvals/provider evidence exist.

### Current staging release and fixture cleanup ? 2026-10-20 18:11 local

- CI run `39424050529` passed for SHA `c1ba25cffca87c703dfce6b4187796e38fe9439c`; protected deploy completed with `SMOKE PASS` and all services healthy.
- Fixture cleanup fix is deployed. The prior fixture was deleted successfully, and a fresh isolated `create` followed by `destroy` returned `deleted=true`. Evidence: `docs/automation/evidence/staging/qa-fixture-create-destroy-c1ba25c.txt`.
- Current Admin boundary run passed 72/72 and CSRF run passed 3/3 on this SHA. Evidence: `docs/automation/evidence/staging/admin-anonymous-boundary-c1ba25c.json`, `admin-csrf-boundary-c1ba25c.json`.
- Authenticated Keycloak/MFA remains unverified; release checker still requires three independent authenticated manifests.

### Current staging release 5eb9fc6 and repeat boundary - 2026-10-20 13:06Z

- CI run `39426955193` passed for SHA `5eb9fc6d6aec94da79c7ff62385b39f191b87e0c`; protected deploy completed and all required containers reported healthy.
- Gateway probes returned Storefront/Seller 200, Admin anonymous 307 and health 200, Keycloak 302. Evidence: `docs/automation/evidence/staging/status-20261020T130602Z.txt` and `gateway-routes-20261020T130602Z.txt`.
- Chromium staging Admin anonymous boundary passed 72/72 across desktop/tablet/mobile; CSRF boundary passed 3/3. Evidence: `admin-anonymous-boundary-5eb9fc6.json` and `admin-csrf-boundary-5eb9fc6.json`.
- The LAN DNS change did not produce fresh ClamAV CDN signatures: service is healthy, but `freshclam` logs still show `Could not resolve hostname`; media gate remains PARTIAL.

### Current staging release ee079032 - 2026-10-20 13:11Z

- CI run `39427746198` completed successfully for SHA `ee079032cfd234ddd3232c4dfc74fc84b1a5bc22`; all six immutable images, PostgreSQL migration/concurrency checks and static checks passed.
- Protected deployment completed and all required services, workers, gateway and Keycloak reported healthy. Evidence: `docs/automation/evidence/staging/status-ee07903-20261020.txt`.
- ClamAV now uses the private `backend` network plus a dedicated non-internal `egress` network. A real EICAR sample returned `Eicar-Test-Signature FOUND`; a clean sample returned `OK`. Evidence: `docs/automation/evidence/staging/clamav-ee079032-20261020.json`.
- Freshclam reaches the upstream CDN but receives HTTP 403 and enters CDN cooldown. Signature freshness and full media quarantine/upload evidence remain PARTIAL; this is not marked PASS.
- Controlled PostgreSQL outage drill on the same runtime returned B2B readiness `503` while the database was stopped, then recovered to `200 {"status":"ok"}` after the container became healthy. No volume was deleted. Evidence: `docs/automation/evidence/staging/db-outage-drill-ee07903-20261020.json`. This is partial dependency-recovery evidence; alerting, retry/DLQ and provider drills remain open.
- Controlled Redis outage drill produced the same fail-closed `503` readiness response and recovered to `200` after Redis became healthy; no volume was deleted. Evidence: `docs/automation/evidence/staging/redis-outage-drill-ee07903-20261020.json`. Alert verification, retry/DLQ and external provider drills remain open.
- A fresh isolated local PostgreSQL restore drill passed for B2C, B2B and Admin. Source/restored row counts and order-independent checksums matched; Admin audit-chain hashes, links and head remained valid. Evidence: `qa-reports/restore-drill/b2b-followup-20261020.json`. This does not close the required off-host WAL/PITR target, encryption, retention or RPO/RTO gate.
- A disposable PostgreSQL integration run applied B2B migrations through `0065_product_safety_holds` and passed 32 DB-backed inventory/export/reservation/outbox tests with zero failures. Evidence: `docs/automation/evidence/staging/b2b-isolated-postgres-integration-20261020.txt` and `.json`. This is isolated local evidence, not a claim against the staging database.
- A second disposable PostgreSQL run passed 7 auth/draft integration tests covering session revocation, draft autosave revision fencing and membership management. Evidence: `docs/automation/evidence/staging/b2b-isolated-auth-draft-integration-20261020.txt` and `.json`.
- A disposable PostgreSQL scale run passed both 100k-row checks: seller inventory pagination completed 1,000 pages with 3.16 MB Python peak, and inventory export wrote 100,001 CSV lines with 1.65 MB worker peak. Evidence: `docs/automation/evidence/staging/b2b-isolated-scale-integration-20261020.txt` and `.json`.
- With separate disposable PostgreSQL and Redis dependencies, carrier/order integration passed 3/3 tests. The carrier dispatch remains intentionally disabled by ADR, while signed webhook ordering and cancellation idempotency were exercised against the current error contract. Evidence: `docs/automation/evidence/staging/b2b-isolated-order-carrier-integration-20261020.txt` and `.json`.

### Deployment confirmation for ee07903 - 2026-10-20 13:10Z

- CI run `39427746198` passed for SHA `ee079032cfd234ddd3232c4dfc74fc84b1a5bc22`; protected deploy completed and all required containers are healthy.
- Gateway probes passed on this SHA. Evidence: `docs/automation/evidence/staging/status-20261020T131059Z.txt` and `gateway-routes-20261020T131059Z.txt`.
- The commit changes only ClamAV updater egress. Anonymous Admin 72/72 and CSRF 3/3 browser evidence remains from immediately preceding code-equivalent `5eb9fc6`; authenticated OIDC/MFA and three manifests remain blocked.

### SSH retry and current deployed boundary - 2026-10-20 18:15Z

- SSH to `market-staging` succeeded again. The read-only audit records Ubuntu host capacity, network, listener, SSH and Docker permission results in `docs/automation/evidence/staging/ssh-retry-audit-20261020T181531.txt`.
- The protected runtime is still pinned to `ee079032cfd234ddd3232c4dfc74fc84b1a5bc22`; all required containers report healthy.
- Chromium Admin anonymous boundary passed 72/72 and CSRF boundary passed 3/3 on this deployed SHA. Evidence: `admin-anonymous-boundary-ee079-20261020T181628.json` and `admin-csrf-boundary-ee079-20261020T181628.json`.
- Gateway and Keycloak discovery probes pass; discovery still advertises only ACR `0`/`1`, so authenticated MFA/step-up remains blocked. Evidence: `gateway-retry-20261020T181841.txt`.

### Current staging release cba15c1 and repeat boundary - 2026-10-20 12:54Z

- CI run `39425351572` passed for SHA `cba15c1aa57641677dc57d1692da8bc38d5f8ac5`; protected deployment completed with all services healthy and `deploy_sha=cba15c1` in API readiness logs.
- Fresh protected status and gateway probes pass for Storefront/Seller/Admin/Keycloak. Evidence: `docs/automation/evidence/staging/status-20261020T125422Z.txt` and `gateway-routes-20261020T125422Z.txt`.
- Chromium staging Admin anonymous boundary passed 72/72 across desktop/tablet/mobile; CSRF boundary passed 3/3. Evidence: `admin-anonymous-boundary-cba15c1.json` and `admin-csrf-boundary-cba15c1.json`.
- Admin unit/integration suite passed 56 with 65 environment-gated skips. Keycloak discovery still advertises only ACR `0`/`1`; authenticated MFA/OIDC and the three independent manifests remain blocked.

### Current live runtime confirmation - 2026-10-20

- The protected staging runtime is currently on immutable image SHA `872b0a1bcfcdac48fb347420502ac92596d0151b`; all required services, workers, gateway and Keycloak report healthy. Evidence: `docs/automation/evidence/staging/status-872b0a1-20261020.txt`.
- The current smoke check returned `SMOKE PASS`. This confirms runtime health only; it does not create authenticated browser evidence.
- Source HEAD is `35ebe3a19eec7e524d2a22d7f233c624eb0592ac`. A protected deploy request failed closed because GHCR does not contain the immutable `admin-frontend` image for that SHA, so no partial promotion was applied and runtime `872b0a1` remains active.
- The latest authenticated Seller browser evidence remains on code-equivalent `ee079032`; no new authenticated route sweep is claimed for `872b0a1`.

### Current live runtime b7e07e7 - 2026-10-20

- After all six immutable images were published by workflow `39433889652`, protected deployment completed on `b7e07e79e8f471f664fdc946683f475eae005772`. All required services, workers, gateway and Keycloak report healthy. Evidence: `docs/automation/evidence/staging/status-b7e07e7-20261020.txt`.
- Real HTTPS health probes returned 200 for Storefront, Seller and Admin; Keycloak realm discovery returned 200 with the configured issuer and JWKS URL. Evidence: `docs/automation/evidence/staging/https-health-b7e07e7-20261020.txt`.
- The authenticated Seller browser sweep remains the earlier code-equivalent `ee079032` evidence; no fresh authenticated browser claim is made for `b7e07e7`.

### Current live runtime d30c5d8 - 2026-10-20

- Workflow `39437627719` passed verify, PostgreSQL integration and all six immutable image builds. Protected deployment completed on `d30c5d843f741213db7d11278bb528c586655b90`; all required services, workers, gateway and Keycloak report healthy. Evidence: `docs/automation/evidence/staging/status-d30c5d8-20261020.txt`.
- Real HTTPS health probes returned 200 for Storefront, Seller and Admin; Keycloak realm discovery returned 200 with the configured issuer and JWKS URL. Evidence: `docs/automation/evidence/staging/https-health-d30c5d8-20261020.txt`.
- The authenticated Seller browser sweep remains the earlier code-equivalent `ee079032` evidence; no fresh authenticated browser claim is made for `20cd369`.

- Fresh current-runtime Seller browser QA completed on `20cd369`: login used an isolated fixture, all 11 protected routes returned HTTP 200 without redirecting to login, the session cookie was HttpOnly, there were no page errors and no unexpected 5xx responses. Finance's 501 responses were the documented fail-closed commercial gate. Evidence: `docs/automation/evidence/staging/b2b-authenticated-routes-20cd369-20261020.json`.
- A separate fixture cleanup check returned `deleted=true` with no credential material recorded. Evidence: `docs/automation/evidence/staging/qa-fixture-create-destroy-20cd369-20261020.json`.
- The B2B regression suite was rerun from source `a720655`: 285 passed, 38 skipped, 0 failed; Ruff also passed. Evidence: `docs/automation/evidence/staging/b2b-regression-a720655-20261020.json`.
- The release checker was rerun from source `71fdfbf`: 202 required cases and zero independent final manifests, so the result remains `BLOCKED`. Evidence: `docs/automation/evidence/staging/release-check-71fdfbf-20261020.json`.
- Current `d30c5d8` staging Chromium axe sweep covered eight authenticated Seller routes at 1440px with zero WCAG 2.2 A/AA violations, page errors or unexpected failed responses. Manual assistive-technology review remains open. Evidence: `docs/automation/evidence/staging/seller-axe-d30c5d8-20261020.json`.


