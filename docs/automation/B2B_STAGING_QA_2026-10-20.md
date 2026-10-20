# B2B staging verification — 2026-10-20

## Version

- Runtime release: \`cba15c1aa57641677dc57d1692da8bc38d5f8ac5\`
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

The Compose release `cba15c1` keeps ClamAV private and adds container-scoped
DNS for the signature updater. The container remains healthy, but the staging
network still cannot resolve/reach `database.clamav.net`; signature freshness
is therefore an open operational blocker and no media-scan gate is promoted.

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
