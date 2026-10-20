# NeoMarket staging blockers

0. **Authenticated QA and release manifests (P0):** local Playwright now trusts the Caddy internal CA and can reach all four staging hosts with Chromium host rules. Anonymous Admin boundary coverage passed 72/72 in all three viewports, but authenticated OIDC/MFA, Seller/Admin workflows, visual comparison and the three independent release manifests are still missing.
1. **Backup/restore (P1):** no approved external backup target or isolated restore drill is configured.
2. **Full functional/security evidence (P1):** media quarantine, order flows, retry/DLQ, concurrency, RBAC and visual acceptance remain unverified on the real staging runtime.
3. **Commercial rules (P1):** ADR-001 is present but remains `PROPOSED / LEGAL_AND_PSP_REVIEW_REQUIRED`; merchant-of-record, tax, refund/restock and PSP settlement flows remain intentionally disabled pending the required approvals/provider evidence. Seller-fulfilled delivery is selected in the proposal, but its legal/commercial gate is not accepted.
4. **Fixture cleanup and refresh (RESOLVED):** after deploy `cba15c1`, the protected fixture runner created and destroyed an isolated authenticated Seller fixture with `deleted=true`; the authenticated state matrix contains no credential material.

Resolved runtime issue: `STAGING-GW-001` was cleared after the root-owned gateway refresh and fixed-SHA redeploy on 2026-10-20. Current evidence: `docs/automation/evidence/staging/gateway-routes-20261020T1801Z.txt` and `status-20261020T1800Z.txt`.

These are evidence-based blockers; no acceptance scenario is marked PASS solely from documentation.
