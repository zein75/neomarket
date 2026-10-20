# B2B staging verification — 2026-10-20

## Version

- Runtime release: \`b0fd2323d8fa5c6df166018f0e5f7c0cfdb4c565\` (current live staging)
- Tested source release: \`b0fd2323d8fa5c6df166018f0e5f7c0cfdb4c565\`; verify/build passed in GitHub Actions run \`39441458390\`, and the protected staging wrapper deployed this immutable SHA. Later documentation commits do not change the runtime image.
- Server: \`192.168.0.112\`
- Gateway: \`127.0.0.1:18080\`
- Environment: isolated staging

## Evidence executed

- Source verification at `ccc04941739e7f679937858f9e7fddc2e31bdfb4`: `uv run pytest services/b2b/tests -q` returned **285 passed, 38 skipped, 0 failed**; `uv run ruff check services/b2b frontend/apps/seller` returned **All checks passed**. Evidence: `evidence/staging/b2b-regression-source-ccc0494-20261020.txt`. The source commit is documentation-only relative to the deployed application image; runtime remains the immutable `b0fd232` release below.
- The release checker was rerun against the current acceptance matrix: **BLOCKED**, 202 required cases, `0/3` independent authenticated manifests. Evidence: `evidence/staging/release-check-ccc0494-20261020.json`. No manifest was fabricated.
- Local B2B regression: **285 passed, 38 skipped, 0 failed**.
- Isolated PostgreSQL integration subset: **32 passed, 0 failed** after applying B2B migrations through `0065_product_safety_holds` in a disposable database.
- Isolated PostgreSQL auth/draft subset: **7 passed, 0 failed** covering session revocation, draft autosave fencing and membership management.
- Isolated PostgreSQL scale subset: **2 passed, 0 failed**; 100,000 SKU cursor pagination used 1,000 pages with 3.16 MB Python peak, and 100,000-row export produced 100,001 CSV lines with 1.65 MB worker peak.
- Isolated PostgreSQL+Redis order/carrier subset: **3 passed, 0 failed** for fail-closed carrier dispatch, signed out-of-order carrier webhook handling and cancellation idempotency. The skipped tests were aligned to the current top-level error contract (`code/message/flow`).
- Ruff: PASS.
- Python compilation: PASS.
- B2B target OpenAPI validation: PASS (76 Admin target operations and 12 B2B Admin target operations).
- Staging B2B \`/health\`: \`{"status":"ok"}\`.
- Staging OpenAPI: 97 paths exposed through the private \`b2b.internal\` gateway host.
- Real staging boundary probes:
  - wrong credentials: \`401\`;
  - seller metrics without session: \`401\`;
  - retired legacy product route: \`410\`;
  - private \`/internal/*\` route through gateway: \`404\`;
  - unauthenticated MFA challenge: \`401\`.
- Host port capture shows only Caddy \`80/443\` publicly bound; NeoMarket gateway and service listeners remain loopback/internal.
- Authenticated Chromium staging sweep: 11/11 protected Seller routes returned HTTP 200 on the requested URL with a real opaque session cookie; no runtime error responses were observed after refreshing the fixture with a valid internal email domain. Axe found no violations on dashboard, products, product-create, inventory, imports, orders, team and settings.
- Current-runtime Chromium axe sweep on `d30c5d8` covered the same eight authenticated Seller routes at 1440px: 0 WCAG 2.2 A/AA violations, 0 page errors and 0 unexpected failed responses. Manual assistive-technology review remains separate evidence work for UI-07.
- Current-runtime Chromium keyboard focus sweep on `0fcb935` covered eight authenticated Seller routes at 1440px: 147 visible controls traversed, 0 invalid focus states, 0 page errors and 0 unexpected 5xx responses. The run used the trusted Caddy CA and an isolated fixture; the two session controls that previously lacked an indicator now expose a 3px solid focus ring.
- The official `seller-keyboard-focus.spec.ts` then ran against `b0fd232` on desktop, tablet and mobile: 9/9 tests passed, with no skipped or unexpected tests. It covered sign-in traversal, navigation reachability and the 13-route product/inventory/order/moderation focus sweep. Evidence: `evidence/staging/keyboard-b0fd232-playwright.json` and `evidence/staging/keyboard-b0fd232/`.
- The official `seller-accessibility.spec.ts` ran against `b0fd232` on desktop, tablet and mobile: 3/3 projects passed, 0 skipped, 0 unexpected. The public and authenticated Seller scans returned zero axe WCAG 2.2 A/AA violations across the tested screens. Evidence: `evidence/staging/axe-b0fd232-playwright.json` and `evidence/staging/axe-b0fd232/`.
- A fresh real staging run of the same accessibility spec passed **3/3** desktop/tablet/mobile projects with an ephemeral fixture and Chromium host mapping; all scans reported zero WCAG 2.2 A/AA axe violations. Credentials were omitted and the fixture was destroyed. Evidence: `evidence/staging/axe-b0fd232-rerun/manifest.json` and the three project JSON results in that directory.
- A fresh real staging run of `seller-keyboard-focus.spec.ts` passed **9/9** tests across desktop/tablet/mobile with zero invalid focus states. The run used the disposable fixture and explicit Chromium host mapping; credentials were omitted and the fixture was destroyed. Evidence: `evidence/staging/keyboard-b0fd232-rerun/manifest.json` and its JSON/PNG artifacts.
- Separate real staging captures for the approved UI-04/UI-05 responsive targets (Pixel 5/390 and Galaxy Tab S4/768) returned HTTP 200 with no horizontal overflow. The captures are isolated from the approved candidate baselines; the two expected session-check 401 console responses are recorded and no visual PASS is asserted from dimensions alone. Evidence: `evidence/staging/ui-04-05-b0fd232/manifest.json` and its four PNG captures.

Evidence files:

- \`evidence/staging/b2b-local-regression-20261020.txt\`
- \`evidence/staging/b2b-runtime-smoke-20261020T120619Z.json\`
- \`evidence/staging/b2b-staging-boundaries-20261020T120530Z.json\`
- \`evidence/staging/port-exposure-20261020T120647Z.json\`
- \`evidence/staging/b2b-authenticated-routes-fbbd473-20261020.json\`
- \`evidence/staging/b2b-authenticated-runtime-fbbd473-20261020.json\`
- \`evidence/staging/csp-fonts-82e1253-20261020.json\`
- \`evidence/staging/status-cba15c1-20261020.txt\`
- \`evidence/staging/seller-state-matrix-cba15c1-20261020.json\`
- \`evidence/staging/status-ee07903-20261020.txt\`
- \`evidence/staging/status-ee07903-after-drills-20261020.txt\`
- \`evidence/staging/status-872b0a1-20261020.txt\`
- \`evidence/staging/status-b7e07e7-20261020.txt\`
- \`evidence/staging/https-health-b7e07e7-20261020.txt\`
- \`evidence/staging/status-20cd369-20261020.txt\`
- \`evidence/staging/https-health-20cd369-20261020.txt\`
- \`evidence/staging/b2b-authenticated-routes-20cd369-20261020.json\`
- \`evidence/staging/qa-fixture-create-destroy-20cd369-20261020.json\`
- \`evidence/staging/b2b-regression-a720655-20261020.json\`
- \`evidence/staging/status-d30c5d8-20261020.txt\`
- \`evidence/staging/https-health-d30c5d8-20261020.txt\`
- \`evidence/staging/seller-axe-d30c5d8-20261020.json\`
- \`evidence/staging/seller-focus-0fcb935-20261020-tls.json\`
- \`evidence/staging/status-0fcb935-20261020.txt\`
- \`evidence/staging/keyboard-0fcb935-playwright.json\` (pre-fix defect evidence)
- \`evidence/staging/seller-focus-diagnose-0fcb935-20261020.json\` (pre-fix moderation filter diagnosis)
- \`evidence/staging/keyboard-b0fd232-playwright.json\`
- \`evidence/staging/status-b0fd232-20261020.txt\`
- \`evidence/staging/axe-b0fd232-playwright.json\`
- \`evidence/staging/axe-b0fd232/\`
- \`evidence/staging/release-check-b0fd232-20261020.json\`
- \`evidence/staging/ui-04-05-b0fd232/manifest.json\`
- \`evidence/staging/clamav-ee079032-20261020.json\`
- \`evidence/staging/smoke-ee07903-20261020.txt\`
- \`evidence/staging/qa-fixture-create-destroy-ee07903-20261020.json\`
- \`evidence/staging/b2b-regression-ee07903-20261020.txt\`
- \`evidence/staging/b2b-authenticated-routes-ee07903-20261020.json\`
- \`evidence/staging/db-outage-drill-ee07903-20261020.json\`
- \`evidence/staging/redis-outage-drill-ee07903-20261020.json\`
- \`qa-reports/restore-drill/b2b-followup-20261020.json\`
- \`evidence/staging/b2b-isolated-postgres-integration-20261020.txt\`
- \`evidence/staging/b2b-isolated-postgres-integration-20261020.json\`
- \`evidence/staging/b2b-isolated-auth-draft-integration-20261020.txt\`
- \`evidence/staging/b2b-isolated-auth-draft-integration-20261020.json\`
- \`evidence/staging/b2b-isolated-scale-integration-20261020.txt\`
- \`evidence/staging/b2b-isolated-scale-integration-20261020.json\`
- \`evidence/staging/b2b-isolated-order-carrier-integration-20261020.txt\`
- \`evidence/staging/b2b-isolated-order-carrier-integration-20261020.json\`
- \`evidence/staging/b2b-regression-source-35ebe3a-20261020.txt\`

The current Compose release `20cd369` keeps the application network internal and adds
a dedicated egress-only network for ClamAV updates. The scanner is healthy and
a real EICAR sample was detected while a clean sample returned OK. The updater
reaches the CDN but is currently rejected with HTTP 403/cooldown, so signature
freshness remains an operational blocker and no media-scan gate is promoted.

Authenticated Seller state sweep on the same release covered 15 real routes:
all returned HTTP 200 with no page errors. Orders showed the truthful empty
state, product creation and onboarding exposed their unavailable dependencies,
returns stayed disabled by ADR policy, and finance returned the explicit
`501 FEATURE_NOT_CONFIGURED` state. The expected 501 responses are retained as
fail-closed evidence; they are not treated as runtime defects. The ephemeral
fixture was destroyed after the run.

The latest authenticated Chromium evidence was collected on the code-equivalent
`ee079032` runtime; it verified 11
protected Seller routes at HTTP 200 with the requested final URLs and no
unexpected 5xx responses. The observed `401` and `501` responses were the
documented fail-closed finance/session checks. The fixture was destroyed with
`deleted=true`; credentials are omitted from the evidence.

The release `82e1253` also corrected the enforced CSP `connect-src` to allow the
Google font stylesheet/font origins already used by the approved Seller,
Storefront and Admin shells. A real Chromium check against all three staging
hosts returned HTTP 200, no CSP/font console violations, no page errors, and
the expected `connect-src` directive.

## Current requirement matrix

- PASS: 87
- PARTIAL: 7
- BLOCKED: 17

The blocked finance and returns requirements remain disabled by the approved commercial decision: merchant-of-record/tax, delivery/returns ownership, refund/restock and PSP/settlement are pending ADR. No fake payment or return implementation was enabled.

Remaining non-commercial evidence gaps:

- \`ID-16\`: bank-change step-up MFA and session-fixation browser evidence.
- \`UI-03\`: authenticated Seller Stitch desktop parity.
- \`UI-06\`: manual screen-reader/modal focus review.
- \`UI-07\`: manual assistive-technology review beyond automated axe.
- \`UI-08\`: complete persisted loading/empty/error state matrix.
- \`SEC-11\`: off-host PITR/restore with checksums.
- \`SEC-14\`: degraded dependency drills and alert evidence.

## Release status

**B2B runtime is deployed and regression-tested. The current `b0fd232` runtime is healthy; the protected status capture shows all required services, workers, gateway and Keycloak healthy. The official Seller focus spec passed 9/9 across desktop, tablet and mobile after fixing the moderation filter focus defect. The full Seller/B2B release remains BLOCKED** until the remaining non-commercial evidence gaps and the ADR-dependent requirements are resolved. ADR-001 is present but still marked `PROPOSED / LEGAL_AND_PSP_REVIEW_REQUIRED`; no finance or return requirement was promoted from documentation alone.
