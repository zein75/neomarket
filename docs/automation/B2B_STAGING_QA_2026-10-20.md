# B2B staging verification — 2026-10-20

## Version

- Runtime release: \`d30c5d843f741213db7d11278bb528c586655b90\` (current live staging)
- Source HEAD: \`f9faaf93de8b01c44bf1521be3283af15f1509cf\`; this HEAD contains documentation-only changes after the deployed `d30c5d8` runtime, which was deployed through the protected staging wrapper.
- Server: \`192.168.0.112\`
- Gateway: \`127.0.0.1:18080\`
- Environment: isolated staging

## Evidence executed

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

**B2B runtime is deployed and regression-tested. The current `d30c5d8` runtime is healthy and the real HTTPS health probes pass. The fresh Chromium Seller fixture evidence was collected on the code-equivalent `20cd369` runtime; it verified 11/11 protected routes, HttpOnly session state, no page errors and no unexpected 5xx responses. The full Seller/B2B release remains BLOCKED** until the non-commercial evidence gaps and the ADR-dependent requirements are resolved. ADR-001 is present but still marked `PROPOSED / LEGAL_AND_PSP_REVIEW_REQUIRED`; no finance or return requirement was promoted from documentation alone.
