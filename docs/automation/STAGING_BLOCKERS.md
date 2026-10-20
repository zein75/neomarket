# NeoMarket staging blockers

1. **Browser trust and authenticated QA (P0):** Caddy uses its internal CA. The current browser environment does not trust that CA, so authenticated OIDC/MFA, Seller and Admin Playwright manifests cannot be run without violating the no-TLS-bypass rule.
2. **Backup/restore (P1):** no approved external backup target or isolated restore drill is configured.
3. **Full functional/security evidence (P1):** media quarantine, order flows, retry/DLQ, concurrency, RBAC and visual acceptance remain unverified on the real staging runtime.
4. **Commercial rules (P1):** merchant-of-record, tax, delivery/returns, refund/restock and PSP settlement flows remain intentionally disabled pending ADR, as previously approved.

These are evidence-based blockers; no acceptance scenario is marked PASS solely from documentation.
