# NeoMarket staging blockers

0. **Browser trust and authenticated QA (P0):** Caddy uses its internal CA. The current browser environment does not trust that CA, so authenticated OIDC/MFA, Seller and Admin Playwright manifests cannot be run without violating the no-TLS-bypass rule.
1. **Backup/restore (P1):** no approved external backup target or isolated restore drill is configured.
2. **Full functional/security evidence (P1):** media quarantine, order flows, retry/DLQ, concurrency, RBAC and visual acceptance remain unverified on the real staging runtime.
3. **Commercial rules (P1):** merchant-of-record, tax, delivery/returns, refund/restock and PSP settlement flows remain intentionally disabled pending ADR, as previously approved.

Resolved runtime issue: `STAGING-GW-001` was cleared after the root-owned gateway refresh and fixed-SHA redeploy on 2026-10-20. Evidence: `docs/automation/evidence/staging/gateway-routes-20261020T115001Z.txt` and `status-20261020T115001Z.txt`.

These are evidence-based blockers; no acceptance scenario is marked PASS solely from documentation.
