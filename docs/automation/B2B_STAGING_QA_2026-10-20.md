# B2B staging verification — 2026-10-20

## Version

- Runtime release: \`c073e7446d6d639f73644a1b68d2110ed234b325\`
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

Evidence files:

- \`evidence/staging/b2b-local-regression-20261020.txt\`
- \`evidence/staging/b2b-runtime-smoke-20261020T120619Z.json\`
- \`evidence/staging/b2b-staging-boundaries-20261020T120530Z.json\`
- \`evidence/staging/port-exposure-20261020T120647Z.json\`

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

**B2B runtime is deployed and regression-tested. The full Seller/B2B release remains BLOCKED** until the non-commercial evidence gaps and the explicitly ADR-dependent requirements are resolved. No requirement was promoted to PASS from documentation alone.

