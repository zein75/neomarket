# Alembic migration strategy (expansion without loss of production data)

Current state: Admin migrations `0001`…`0006` exist. B2B currently has flat Category fields; do **not** rewrite old revisions or reuse numbers. All concrete migrations must be authored against existing DB metadata and tested on anonymized DB snapshot.

## Stage A — Safety and constraints

- Baseline existing schema and actual heads in CI/staging. Backup database + test restore **before** migration.
- Record current product statuses, category IDs, images and moderation rows; check orphans/duplicate `(product_id,rev,kind)`, invalid slugs, cycles, outbox stuck, missing receipts. Produce migration validation report; stop on unresolved anomalies.
- Create new tables/indexes additively, concurrently where supported; no premature `NOT NULL` on historical data.

## Stage B — Admin identity / moderation

1. `staff_principals` mapping `(issuer,subject)` string + internal UUID, role grants and audit.
2. New `ticket_revision`, `snapshot_hash`, `snapshot_ref`, `version`, `lease_expires_at`, `lease_token_hash`, `fencing_version`; or separate `moderation_leases` table. Never populate fake snapshot hash; backfill from actual B2B immutable version data, else mark historical ticket `REVALIDATION_REQUIRED`.
3. `moderation_decisions`: immutable decision row, request_hash, idempotency_key, unique scoped constraints, `delivery_status`; link to version/lease.
4. Backfill existing `moderation_cards` and outbox after reconciling B2B status. Inconsistent rows quarantined, not auto-approved.
5. Add partial/unique indexes only when duplicates resolved. Introduce new strict endpoints under `/admin/v1`; deprecate and eventually remove legacy routes after clients migrate.

## Stage C — B2B taxonomy v2

1. Add `category_versions`, localization names, code, path/closure, display order, status, redirect table; keep `categories.is_active` and old slug temporarily as derived compatibility projection.
2. Add `attribute_definitions`, `category_attribute_rules`, `taxonomy_change_receipts`, optional `product_revisions` and `product_publications` in B2B.
3. Validate existing parent chains and cycles before closure/path construction; category slug conflict/collision report; orphan `product.category_id` report (currently no ORM FK). Backfill with stable UUIDs, never reassign silently.
4. Introduce new write command and effective taxonomy version while maintaining compatible B2B read APIs.
5. Product write routes validate against category schema v2. Old products grandfathered until explicitly migrated according to approved policy; no retroactive unpublished state without policy.
6. Switch Admin new category UI to v2. Measure public catalog/index reconciliation against B2B for 7+ days of real staging simulation where feasible.
7. Contract phase: remove legacy category fields/routes only after telemetry proves unused, and approved backout horizon expires.

## Stage D — Complaints / appeals / brands / bulk

Separate migrations with FKs, version fields, indexes, encrypted evidence references and retention. Audit tables append-only: DB privileges remove UPDATE/DELETE from application role, background archive/export through controlled admin job.

## Stage E — Rollout and rollback

- Expand (old and new readers) → dual-read verification or one-way projection with checksums (avoid dual authoritative writes) → backfill batches → switch reads → contract.
- Migration transaction vs `CONCURRENTLY` special cases handled explicitly. For long locks, lock timeout + safe abort.
- Each version documented with forward SQL/Alembic, test fixtures, prior/after row counts, known impact and rollback semantics. Rollback code + schema only if reversible; otherwise roll-forward with repair job.
- On event schema upgrade, keep v1 consumer adapter until producer/consumer coverage reached. Event replay after restore must preserve idempotent receipts and old aggregate version.
- CI checks: fresh empty DB upgrade, historical anonymized snapshot upgrade, repeat job safety, source/destination checksum, downgrade when supported, recovery drill.

## Acceptance

No unexplained dropped rows, no lost product/category IDs, referential integrity checked, historical decisions queryable, rollback/rollforward rehearsed, backup restore drill passes, all migrations pinned and scanned before release.
