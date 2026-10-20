# Execution plan — dependencies, files, deliverables

Baseline: `neomarket-full-audit-2026-10-16.zip`, target GitHub monorepo `market`. Old canon ignored. Each phase deliver actual code, migration, API contract, proof; next phase only after gate.

| Phase | Priority | Deliverables | Primary files/modules | Gate |
|---|---|---|---|---|
| A0 Inventory + ADRs | P0 | freeze snapshot; extract current FastAPI OpenAPI; audit conflicting aliases; resolve category ownership, moderation policy, IdP selection, approval separation, taxonomy rollout | `services/admin`, `services/b2b`, `frontend/apps/admin`, `docs/design-system` | G0 |
| A1 Admin identity | P0 | real OIDC auth-code+PKCE callback, string subject mapping, session BFF, MFA & step-up, permissions policy, no dev bypass | `frontend/apps/admin/middleware.ts`, `app/login`, new `app/api/auth/*`, `services/admin/src/api/deps.py`, models/migrations | G1 |
| A2 Moderation data integrity | P0 | immutable product revisions/snapshots, CAS, claim token/lease/fencing, idempotent decisions, case notes + immutable audit | `services/admin/src/models/moderation.py`, schemas, repo, moderation_service, router; B2B product models/services and Alembic | G2 |
| A3 Event delivery | P0 | separate moderation worker, versioned envelopes, B2B inbox ack, retries/DLQ, reconciliation service and monitoring | `services/admin/src/main.py`, new `workers/*`, `services/b2b/src/api/routers/moderation_events.py`, CI | G2/G6 |
| A4 Core Admin UI | P1 | Stitch-accurate queue/detail, claim/heartbeat, field diffs, SKU/media, decisions and status tracking, no fakes | `frontend/apps/admin/app/*`, shared UI/api-client/auth, Playwright | G4 |
| A5 Category model/API | P1 | authoritative B2B taxonomy v2, categories CRUD/status/tree, validation, SQL constraints, impact preview, audit | `services/b2b/src/models/category.py`, `services/category_service.py`, new admin command routes, migrations | G3 |
| A6 Attribute rules + brands | P1 | typed attribute schemas, category inheritance, validation in seller write and moderation, brands registry, duplicate review | B2B models/schemas/services, B2B API + Admin BFF | G3 |
| A7 Category/brand UI | P1 | Stitch-aligned tree editor, drag proposal, schema builder, preview/maker-checker, version history | `frontend/apps/admin/app/taxonomy/*`, shared form/ui | G3/G4 |
| A8 Seller compliance | P1 | seller review, staff permissions, restriction rules, notifications, open-order safe handling | new `services/admin` seller module, B2B seller APIs | G5 |
| A9 Complaints/appeals/reasons | P1 | triage/evidence/investigation; independent appeal reviewers, reason library, case timeline | new admin tables/migrations/services, frontend | G5 |
| A10 Bulk/ops/audit | P1 | dry-run, maker-checker, durable jobs/replay, audit filter+immutable export, incidents | new admin ops, CI, UI and observability | G5/G6 |
| A11 Full QA | P0 before release | role/security matrix, race tests, Testcontainers/PostgreSQL, deterministic screenshot baselines, WCAG, load and DR | `qa/`, `services/*/tests/`, `frontend/e2e/`, GitHub workflows | G7 |
| A12 Staging → production | release | real IdP, privacy/legal signoff, migration rehearsal, backups, monitoring and manual go/no-go | `deploy/`, runbooks, github workflows, configuration | G6/G7 |

## Cross-cutting engineering rules

1. No stage is "done" from TypeScript compilation alone. Start actual apps, use real seeded test backend and Playwright MCP. Missing API → implement with approved B2B/Admin schema or BLOCKED (never fake).
2. Keep B2B as category and product source of truth. Do NOT clone its SQL tables as writeable Admin shadow state.
3. Preserve existing SKU reservation, order and moderation outbox guarantees when migrating published product statuses. Integration regression on B2C checkout mandatory when changed.
4. Make each stage independently deployable via expand/contract; feature flags default OFF until full contract/data migration ready.
5. Every mutation returns explicit HTTP status and problem detail, uses server auth and idempotency / optimistic version validation.
6. Security changes precede opening Admin publicly. Individual staff permissions cannot be inferred from role label stored in browser.
7. Minimize request sizes, rate-limit, cap page size and avoid API proxy bypass/SSRF from user-provided URLs.
8. Use stable consistent UI components/tokens; compare PNG/HTML at reference CSS size. For new pages absent from Stitch, extend Design System through an approved ADR and corresponding new baselines.
9. Update `qa/ACCEPTANCE_MATRIX.csv`, `audit/RISK_REGISTER.csv`, report after each iteration. Repeat three independent full relevant suites after last modification. Maintain progress file for context recovery.

## Delivery format per iteration

- Problem/requirement IDs and exact touched files.
- Data migration and backout/rollforward strategy.
- Current API generated OpenAPI diff and contract test.
- Code + unit + PostgreSQL integration + negative permission tests.
- Browser trace/screenshots, visual comparison.
- Three independent final QA runs with hashes and timestamps.
- Known unresolved issues and exact next task.

If a business policy must be chosen (supported category hierarchy, appeal deadlines, evidence retention, moderation SLA, identity provider, staff regions), create a short ADR describing options and consequences; do not silently invent jurisdiction-specific legal terms.
