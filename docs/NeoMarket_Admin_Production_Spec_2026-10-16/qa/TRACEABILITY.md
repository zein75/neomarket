# Traceability conventions

## Audited source → spec → code → test

- Audit input source snapshot: `neomarket-full-audit-2026-10-16.zip`.
- Existing Admin API: `services/admin/src/api/routers/moderation.py`; authentication `api/deps.py`; existing models/repo/service; Admin Next `frontend/apps/admin/`.
- Existing B2B category: `services/b2b/src/models/category.py`, `api/routers/categories.py`, `services/category_service.py`.
- Current design: `docs/design-system/stitch/admin-panel/reference.png`, `source-official.html`.
- Proposed Admin BFF contract: `contracts/admin-target.openapi.yaml` (73 operations, including four source-backed authentication/session/export routes, integration status, runtime settings inventory and versioned settings proposals; this remains a proposed contract, not runtime evidence).
- Proposed B2B internal protocol: `contracts/b2b-admin-internal-target.openapi.yaml` (8 operations).
- `audit/RISK_REGISTER.csv`: 69 defect/risk records keyed `ADM-###` with source and required fix. Source_CONFIRMED vs RISK_TO_TEST distinct.
- `qa/ACCEPTANCE_MATRIX.csv`: 197 scenarios `AT-###`, each tagged with requirement prefix. Scenarios remain `NOT_RUN` until executed with evidence; individually verified scenarios link their persisted run artifact.
- Progress per iteration: `docs/automation/ADMIN_PROGRESS.md` in implementation repo, with requirement ID, commit, modified files, actual OpenAPI diff, test IDs/CI artifact links and screenshot diffs.

## Review and evidence

- `SOURCE_MITIGATED_RUNTIME_VERIFIED` and `PARTIALLY_MITIGATED_RUNTIME_VERIFIED` mean the linked isolated runtime scenario ran successfully; they do not imply offsite/staging readiness or satisfy the three independent Playwright release runs. `PARTIALLY_*` retains explicit unverified requirements.

For each implemented new API and screen, register at least one positive E2E scenario, one expected failure and negative access test. For core operations use two concurrent clients and one lost network response. Tests MUST execute actual backend with dedicated PostgreSQL; mocks are acceptable only for isolated unit/component tests.

The `qa/check_release.py` script demands evidence from three distinct independent runs for every acceptance ID. It checks manifest shape, not the authenticity of test execution — the pipeline must generate manifests from actual CI test outputs in separate clean job executions, store append-only artifacts, and review the release sign-off.
