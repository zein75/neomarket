# B2B staging verification — 2026-10-20

## Version

- Runtime release: \`ee079032cfd234ddd3232c4dfc74fc84b1a5bc22\`
- Server: \`192.168.0.112\`
- Gateway: \`127.0.0.1:18080\`
- Environment: isolated staging

## Evidence executed

- Local B2B regression: **285 passed, 38 skipped, 0 failed**.
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
- \`evidence/staging/clamav-ee079032-20261020.json\`
- \`evidence/staging/smoke-ee07903-20261020.txt\`

The Compose release `ee079032` keeps the application network internal and adds
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

**B2B runtime is deployed and regression-tested. Authenticated Seller route access is now verified on the current release. The full Seller/B2B release remains BLOCKED** until the non-commercial evidence gaps and the ADR-dependent requirements are resolved. ADR-001 is present but still marked `PROPOSED / LEGAL_AND_PSP_REVIEW_REQUIRED`; no finance or return requirement was promoted from documentation alone.
