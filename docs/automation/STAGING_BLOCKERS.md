# NeoMarket staging blockers

0. **Authenticated QA and release manifests (P0):** local Playwright now trusts the Caddy internal CA and can reach all four staging hosts with Chromium host rules. Anonymous Admin boundary coverage passed 72/72 in all three viewports, and the current `45ebbae` runtime now has fresh authenticated Seller evidence for 11/11 protected routes. Authenticated OIDC/MFA, Admin workflows, visual comparison and the three independent release manifests are still missing.
1. **Backup/restore (P1):** isolated local B2C/B2B/Admin restore drill now passes with matching counts/checksums and a valid Admin audit chain, but no approved external target, WAL/PITR, retention or RPO/RTO is configured.
2. **Full functional/security evidence (P1):** media quarantine, order flows, retry/DLQ, concurrency, RBAC and visual acceptance remain unverified on the real staging runtime. The ClamAV daemon is now reachable through the isolated egress network and rejects EICAR, but signature refresh is blocked by the upstream CDN's HTTP 403/cooldown.
3. **Commercial rules (P1):** ADR-001 is present but remains `PROPOSED / LEGAL_AND_PSP_REVIEW_REQUIRED`; merchant-of-record, tax, refund/restock and PSP settlement flows remain intentionally disabled pending the required approvals/provider evidence. Seller-fulfilled delivery is selected in the proposal, but its legal/commercial gate is not accepted.
4. **Fixture cleanup and refresh (RESOLVED):** after deploy `ee079032`, the protected fixture runner created and destroyed an isolated authenticated Seller fixture with `deleted=true`; evidence contains no credential material.

Resolved runtime issue: `STAGING-GW-001` was cleared after the root-owned gateway refresh and fixed-SHA redeploy on 2026-10-20. The current live runtime is `45ebbae`; evidence is `docs/automation/evidence/staging/status-45ebbae-20261020.txt`. Runtime status was revalidated after the protected deployment to `45ebbae`; fresh Seller accessibility (3/3) and keyboard/focus (9/9) evidence is recorded under `docs/automation/evidence/staging/axe-45ebbae-rerun/` and `docs/automation/evidence/staging/keyboard-45ebbae-rerun/`.

These are evidence-based blockers; no acceptance scenario is marked PASS solely from documentation.

