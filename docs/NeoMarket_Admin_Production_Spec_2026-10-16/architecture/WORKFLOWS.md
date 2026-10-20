# Product and operational workflows (normative)

## W1. Seller submits a product for moderation

**Given** existing seller + valid category rules + real media refs. Seller saves draft product rev N. B2B validates category schema, required attributes, SKU fields, media state and seller eligibility. B2B commits product revision + outbox `product.revision.submitted` in one DB transaction. Admin consumes event via inbox: verify producer+schema, compare event hash/id, persist immutable snapshot, open new ticket; duplicate is NOOP, payload mismatch is conflict. Notify UI queue; do not expose draft to public catalog. Stale or out-of-order events trigger reconciliation job.

## W2. Moderator review / approval

1. Principal authenticates via OIDC/MFA; Admin BFF verifies server-side session and grants.
2. GET queue, open ticket, see immutable product snapshot and source media, compare with published revision.
3. Claim lease with new random token, version and expiration; only current owner can decide.
4. Field checklist + automatic rule results. Unknown mandatory category rules → no approval.
5. Decision `APPROVE` with `Idempotency-Key`, `If-Match`, `claim_token`, `product_revision` and policy_version. Server transaction verifies lease, revision, permissions, checks, payload hash and saves decision + audit + outbox.
6. Response `202`, `operation_id`, state `DECISION_PENDING`. B2B applies only if current submitted revision/policy valid and product/seller/category rules pass; writes event receipt and publication change transactionally.
7. Admin marks `DECIDED` after ack/correlated event; B2C/search projection refresh; UI shows `PUBLICATION_PENDING` until publicly queryable.
8. Failure: outbox retries with exponential backoff, DLQ after policy threshold, operator reconcile view. **Never** display «Опубликовано» on accepting command alone.

## W3. Reject/request changes

`CHANGES_REQUESTED`: add actionable field reports (`field_path`,`sku_id`/`media_id`,`reason_code`,`explanation`); preserve old published revision (if legally safe) and do not silently block it. Seller sees reports and edits new revision. `REJECT`: cannot be published, message to seller; `HARD_BLOCK`: senior permission, explicit policy/justification, separate effect on existing publication, maker-checker if wide impact. Seller can appeal via separate workflow. Every notification carries stable event_id and recipient scope.

## W4. Concurrent moderators

A claims ticket; B claim receives 409. A lease expires; B claims and increments fencing. A attempts approve with old token/revision → 409/412; no decision/outbox/audit of approval. Concurrent retry with same key/payload returns previous decision; same key/different payload → 409. Two tabs of same moderator also subject to version check. DB concurrency tests with barriers, no mocked repository in primary integration suite.

## W5. Create category

Taxonomy editor opens `/taxonomy/categories/new` and selects parent, localized names, code/slug, state, SEO, media, optional attribute schema. Server validates no collision/path cycle, validates parent ACTIVE/DRAFT policy, previews child URL/path and filter inheritance, saves proposal as DRAFT; appropriate approver publishes with `If-Match`, step-up/MFA and maker-checker for high-impact. Admin BFF sends signed command to B2B. B2B creates category+version in its DB, emits `taxonomy.category.published`; search/B2C cache update; UI polls operation and shows latest authoritative tree. Failure → operation recorded with per-step reason, retries/reconcile, never phantom successful category.

## W6. Move/merge/archive category

GET impact preview: subtree size, direct+descendant published products, taxonomy schema changes, redirects, affected sellers, search filters, re-moderation count. Approval → idempotent background job with per-batch progress, checkpoint, retry and audit; cannot move root into descendant or delete referenced entity. Migration strategy for required attributes defined per affected product (keep grandfathered schema / require re-review). Archive only after all blocking dependencies resolved. Rollback restores prior taxonomy version and redirects where feasible; irreversible external effects explicitly documented.

## W7. Change category attribute requirements

Edit schema DRAFT; typed constraints; inheritance/override preview; migration compatibility report. If `required` changes from false to true and published products lack value, choose explicit policy: grandfather, block new submissions only, or batch re-review. Without policy approval, publish prohibited. Version published atomically in B2B + event to projections. Validations are enforced in product creation AND revision moderation, not only frontend.

## W8. Safety hold and seller suspension

Trusted reviewer files risk report, triage with evidence, applies scoped temporary hold to product/seller with reason, expiry, audit and seller/buyer impact assessment. Product publication temporarily hidden; open orders not cancelled automatically, obligations handled by separate order process. Suspension escalates to seller compliance and maker-checker if critical; appeals review by independent staff. Reinstatement does not bypass latest product/category checks.

## W9. Complaint and appeal

Intake from B2C/seller/admin event → dedupe (reporter privacy), ticket, priority, attachments evidence hash + AV scan. Case assignment and legal/workflow timer. Reviewer resolves with reason and notice; if appeal, original decision immutable, independent reviewer checks evidence and creates new corrective decision. Retention policy and access audit apply. No algorithmic irreversible bans based only on heuristic flag.

## W10. Bulk edit / incident response

Operator uploads or selects IDs; backend locks a selection revision; runs dry-run with typed validation and estimated blast radius; maker-checker approves; asynchronous operation handles each item independently with durable receipts. Progress page (`processed`, `succeeded`, `failed`, `skipped`, `cancel_requested`), downloadable redacted results; retries don't duplicate effects. Alert on abnormal volume or retry/permission failures. Every mass action must be traceable to two principals for high-impact classes.
