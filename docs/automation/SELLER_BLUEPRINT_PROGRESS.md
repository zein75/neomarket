# Seller Blueprint implementation progress

**Blueprint:** `docs/NeoMarket_Seller_Production_Blueprint_2026-10-16/`  
**Release status:** `NO-GO` вЂ” this log tracks local implementation work and does not replace the blueprint's release gates.

## Current iteration

### S-01 вЂ” atomic product and first SKU creation

- Added seller command `POST /api/v1/seller/products/with-first-sku` and a same-origin Seller BFF route.
- Product, first SKU, moderation outbox event, and idempotency receipt are written in one database transaction. The old two-request UI flow and compensating DELETE are removed.
- `Idempotency-Key` is scoped by seller and bound to a canonical request hash. A retry replays the created product; reuse with a different body returns `409 IDEMPOTENCY_CONFLICT`.
- The browser retains the key by request fingerprint after an ambiguous network failure and clears it after a successful response.
- Status: **implemented and verified in the local PostgreSQL/browser flow; concurrent retries and release-scale verification pending**.

### S-02 вЂ” stock adjustment idempotency

- Keys are now scoped by seller; request identity covers seller, SKU, delta, and reason.
- A duplicate matching request replays the stored on-hand/reserved result. Reusing a key with a different payload returns `409 IDEMPOTENCY_CONFLICT`.
- A database uniqueness race rolls back the losing transaction before it reads and replays the winner.
- Migration `0029_stock_adjustment_idempotency` backfills request hashes for existing keyed adjustments online. Legacy result quantities remain nullable because their historical outcome cannot be reconstructed from the current SKU row.
- Status: **implemented and verified in the local PostgreSQL/browser flow; concurrent key races and production-scale verification pending**.

### S-03 вЂ” product revision check

- Added persistent integer `products.revision` with migration `0031_product_revision` and exposed it in product responses.
- All product mutation HTTP paths now require integer `If-Match`. The seller update service locks the owner-scoped product row, compares the expected revision while holding that lock, and advances the revision in the same transaction.
- Stale edits return `409 REVISION_CONFLICT`; wildcard `If-Match` is rejected because it cannot prevent lost updates.
- Status: **implemented and migrated locally; two-writer concurrency verification pending**.

### S-04 вЂ” SKU revision check

- Added persistent integer `skus.revision` with migration `0032_sku_revision` and exposed it in SKU responses.
- All SKU update HTTP paths now require integer `If-Match`. The update service locks the SKU row, compares the expected revision, then increments the revision in the transaction.
- Stale edits return `409 REVISION_CONFLICT`; wildcard revisions are rejected.
- Status: **implemented and migrated locally; two-writer concurrency verification pending**.

### S-05 вЂ” seller allocation projection (partial)

- B2C checkout now snapshots the SKU owner and writes one seller allocation event per seller into a durable outbox in the same transaction as the buyer order.
- The event carries only the allocation, seller, order-line snapshots, currency, and amount fields. It excludes buyer identity, address, and contact data. Delivery uses the existing authenticated service channel and retries from the B2C worker.
- B2B verifies the allocation payload hash, stores an inbox receipt and the seller-owned order/items in one transaction, and deduplicates replays. Seller list/detail API queries always scope by the authenticated seller; list cursors are signed and tenant-bound.
- Seller `/orders` and `/orders/[id]` are connected through same-origin BFF routes. They show the server state `CREATED` and explicitly state that payment is unconfirmed. No accept, pack, ship, delivery, or recipient data is exposed.
- Status: **allocation projection implemented and verified locally; fulfillment transitions, shipments, cancellation/returns, tax snapshot semantics, backfill/reconciliation, and provider-backed delivery remain incomplete. This is not G4 PASS.**

### S-06 вЂ” bounded seller inventory and server metrics

- Added owner-scoped `GET /api/v1/seller/inventory` with one SQL statement for the bounded SKU page and aggregate summary, keyset pagination by product/SKU IDs, and indexes on seller products and SKUs.
- Cursors are HMAC-signed and bound to seller, query, and status filter. Search and availability filters run in B2B; the Seller BFF forwards a single requested page instead of draining up to 10,000 products into memory.
- Added `GET /api/v1/seller/dashboard/metrics`; Dashboard KPI totals and `as_of` now come from server aggregates. The product preview labels the 100-product limit and links sellers to the fully paginated Inventory screen.
- Inventory UI displays the server summary, search/status filters, and previous/next cursor pages. Stock adjustments retain seller-scoped idempotency and server confirmation.
- Status: **local API/BFF/browser flow verified; the required 100k-SKU load profile, PostgreSQL concurrency suite, and full G3 gate remain unverified.**

## Verification evidence

- Full B2B test suite after S-06: **191 passed, 3 skipped**. The skipped tests require `NEOMARKET_POSTGRES_TEST_URL` and exercise concurrent PostgreSQL inventory operations.
- Full B2C test suite after this iteration: **148 passed, 4 skipped**. The skipped tests require `NEOMARKET_POSTGRES_TEST_URL` and exercise PostgreSQL checkout concurrency.
- Seller allocation unit checks: cursor signature/tenant binding and PII-minimized allocation payload; **2 passed**.
- Local PostgreSQL databases are at `b2b: 0034_seller_inventory_indexes` and `b2c: 0033_seller_order_outbox`.
- Local B2C outbox в†’ authenticated B2B inbox integration: **1 delivery, 1 allocation row, 1 line row, inbox `PROCESSED`; duplicate event returned accepted=false**. Synthetic database rows were deleted after verification.
- Real Playwright seller allocation list/detail flow: **3/3 passed** across desktop, tablet, and mobile. The browser read the live seller-scoped B2B projection and verified the unconfirmed state and absence of recipient/address fields. Screenshots are in `docs/automation/evidence/seller-order-detail-*.png`.
- Real Playwright inventory and dashboard flows: **6/6 passed** across desktop, tablet, and mobile. They exercised the same-origin BFF, live PostgreSQL-backed summary, keyset next page, filter-bound cursor rejection, and accurate Dashboard metrics. Screenshots are in `docs/automation/evidence/seller-inventory-cursor-*.png`.
- Seller TypeScript typecheck and Ruff on changed Python files: passed.
- Python compilation: passed for the edited B2B source and migrations.
- Seller TypeScript typecheck: passed (`tsc --noEmit -p apps/seller/tsconfig.json`).
- Alembic online upgrade on the local `neomarket` development database: **passed** through `0034_seller_inventory_indexes`; the current B2B revision is `0034_seller_inventory_indexes`. An initial attempt exposed the 32-character Alembic version column limit; the IDs were shortened and the failed transactional migration rolled back before retry.
- Saved the live local B2B `/openapi.json` as `docs/automation/evidence/b2b-openapi-s06-2026-10-16.json`; the running schema contains both seller inventory and dashboard metrics routes.
- Alembic offline SQL generation through head: passed. The offline path intentionally cannot backfill historic stock request hashes; the online migration performs that backfill.
- Playwright in a real browser: seller creation form/dashboard passed on desktop, tablet, and mobile; inventory reason length passed on desktop/tablet/mobile; atomic product+SKU creation, identical-key replay, stock adjustment replay after a later adjustment, and mismatched-payload conflict passed on desktop/tablet/mobile. The BFF also rejects a mutation without CSRF (1/1 desktop). These are focused checks, not three independent full release runs.
- **Not verified:** simultaneous PostgreSQL writers/retries; three independent full release runs; the remaining G0вЂ“G8 gates.
- Run metadata: `docs/automation/seller_runs/2026-10-16/0943z-s05-allocation-metadata.json` and `docs/automation/seller_runs/2026-10-16/1011z-s06-inventory-metadata.json`.

## Defects found and fixed in this iteration

- Migration IDs longer than Alembic's existing `version_num` column caused the first local migration attempt to fail. PostgreSQL rolled back the entire transaction; shorter IDs migrated successfully.
- The Seller local environment lacked `NEOMARKET_CSRF_SECRET`, so the create form stopped before issuing its BFF request. A random development-only value is now set in the ignored local `.env.local`, and the environment template documents the required server-only setting.
- Atomic create initially passed `ProductImageCreate` values into `SKUCreate`, which expects `SKUImageCreate`. The request mapper now converts image fields explicitly; the browser flow exercises it.
- Stock reason input limits are aligned at 64 characters in the Seller UI, BFF, and API schema.
- The seller-order DTO initially exposed the buyer master-order UUID; it was removed so seller projections cannot correlate another seller's allocation.
- Inventory BFF initially drained at most 100 pages and returned a complete-page signal even when the owner had more products. It now returns one requested cursor page, with explicit pagination in Inventory; the Dashboard preview discloses its 100-product cap and uses separate server-wide KPI aggregates.
- The first live inventory query returned 500 because three aggregate fields were omitted from the SQL projection. The browser run caught it; the projection was corrected and the final desktop/tablet/mobile run passed.

## Remaining release blockers

The source risk register remains authoritative and unchanged. Seller commerce is not production ready: seller tenancy/RBAC and managed sessions, media quarantine, category-driven schema validation, bulk import/export and ledger reconciliation, 100k-SKU load/concurrency evidence, seller order fulfillment and reconciliation, returns, merchant settlement/PSP/legal decisions, approved responsive Stitch baselines, production security/DR exercises, and all release sign-offs remain open or unverified. Allocation read projection is implemented locally, but it does not satisfy G4. No carrier or payment provider has been selected or simulated.

Do not mark a source risk or blueprint gate `PASS` based on compilation, unit tests, an offline migration, or a UI page load. Update this log only with evidence from the relevant real database/browser/integration gate.

### S-06 focused browser rerun вЂ” 2026-10-16 10:22 UTC

- Repeated Inventory and Dashboard checks after restarting only the Seller Next dev process with the current `.env.local`: **6/6 passed** across desktop, tablet, and mobile. The checks exercised real Seller BFF routes and the local PostgreSQL-backed B2B API.
- This clears the prior local test-environment failure. It does not close INV-16: 100k-SKU performance and no-truncation verification are still PARTIAL; PostgreSQL concurrency and three independent full release runs are unverified.
- Run record: `docs/automation/seller_runs/2026-10-16/1022z-s06-inventory-browser-recovery.json`. The three screenshots were refreshed in `docs/automation/evidence/`.

### G3 PostgreSQL reservation integration subset вЂ” 2026-10-16 10:24 UTC

- Ran the three previously skipped `test_postgres_*` cases against an isolated `b2b_s06_inventory` database migrated through `0034_seller_inventory_indexes`: **3 passed, 22 deselected**. Covered multi-SKU reserve/replay, same-key payload conflict, and parallel same-key reserve idempotency.
- Dropped the isolated database after the run; no test fixtures remain in local marketplace databases.
- These tests exercise the B2B reservation service and PostgreSQL behavior; they do not prove seller stock-adjustment concurrency, reserve-vs-adjustment safety, 50 concurrent increments, or any complete INV requirement. No matrix item was marked PASS from this subset.
- Run record: `docs/automation/seller_runs/2026-10-16/1024z-g3-reservation-postgres.json`.

### G1 logout-all evidence update вЂ” 2026-10-16 10:57 UTC

- Re-ran the exact logout-all Playwright scenario against local Seller/B2B and a disposable seller: **3/3 passed** across desktop/tablet/mobile. The test proved the BFF cookie is cleared and the previously issued JWT receives 401. The one created seller row was deleted after the run; no credential was retained.
- Re-ran live Dashboard metrics and inventory control scenario: **3/3 passed** across desktop/tablet/mobile.
- Ruff and git diff --check passed. A fresh live B2B OpenAPI snapshot is saved at docs/automation/evidence/b2b-openapi-sessions-2026-10-16.json and contains POST /auth/logout-all.
- ID-15 is marked PASS in the requirement matrix from this browser run plus the existing isolated PostgreSQL/session and JWT checks. G1 remains open: logout-all JWT versioning is not the target opaque BFF session design; invitations, membership/RBAC, MFA, email verification/recovery, device sessions, session fixation, and the rest of identity coverage remain unverified. Release remains NO-GO; no full independent release Playwright runs were executed.
- TypeScript check was not run because the current frontend 
ode_modules lacks TypeScript.
- Run record: $run.

### G1 pre-login cookie rotation check вЂ” 2026-10-16 11:00 UTC

- Added a browser check that seeds a stale access cookie before login, signs in, confirms the BFF replaced it, then reads the authenticated session. Together with logout-all, both auth checks passed on desktop, tablet, and mobile: **6/6**.
- The disposable seller was removed after the run (one exact row deleted). No credentials were retained.
- ID-16 is PARTIAL: the session fixation sub-case passed; finance-action step-up MFA is not implemented. G1 remains partial and release remains NO-GO.
- TypeScript package is absent from the current frontend node_modules, so the application typecheck is not run. Playwright successfully compiled/executed the changed E2E source.
- Evidence: $meta and $report.

### G1 access-cookie expiry correction вЂ” 2026-10-16 11:03 UTC

- Fixed the Seller BFF access cookie lifetime from 3600 seconds to 900 seconds to match the B2B access JWT (15 minutes).
- Browser E2E verified the cookie expiry is between 14 and 15 minutes after login, that pre-authentication cookie state is replaced, and that logout-all invalidates the previous token: **6/6 across desktop/tablet/mobile**.
- The first TTL assertion tried to read Set-Cookie from browser response headers; Playwright does not expose that header. The failed run is retained as docs/automation/seller_runs/2026-10-16/1101z-g1-auth-playwright.json; the corrected browser-cookie expiry assertion passed in docs/automation/seller_runs/2026-10-16/1102z-g1-auth-playwright.json.
- IDs: ID-15 PASS; ID-16 PARTIAL (session fixation covered, finance step-up MFA missing). G1 remains PARTIAL; release NO-GO. TypeScript typecheck remains not run because TypeScript is absent from the current frontend node_modules.
- Run metadata: $run.

### G1 API-aligned cookie expiry + final browser evidence вЂ” 2026-10-16 11:07 UTC

- Refreshed live B2B OpenAPI; confirmed `POST /auth/logout-all` and `TokenResponse.expires_in` are present.
- With the rebuilt B2B API, logout-all, stale pre-login cookie replacement, and browser cookie expiry checks passed: **6/6**, 0 failed, 0 skipped across desktop/tablet/mobile. Disposable seller fixture was removed; no production data was used.
- ID-15 remains PASS; ID-16 remains PARTIAL because finance-action step-up MFA is missing. G1 remains PARTIAL and release remains NO-GO. TypeScript check was not run because the package is absent.
- Run metadata: `docs/automation/seller_runs/2026-10-16/1107z-g1-auth-security-metadata.json`; Playwright report: `docs/automation/seller_runs/2026-10-16/1107z-g1-auth-playwright.json`.

### G1 login abuse throttle вЂ” 2026-10-16 11:16 UTC

- Added a Redis Lua fixed-window limiter for normalized email and direct socket IP. Identifiers are HMAC-hashed; Redis failure denies login with 503. Eight failures per account and twenty attempts per IP are permitted per 15-minute window; subsequent attempts return 429 and `Retry-After`. Successful login clears the account counter.
- Real local B2B/Redis endpoint run: eight bad-password requests returned 401, the next returned 429 with `Retry-After: 900`; synthetic Redis counters were removed after the run. Unit tests: 12 passed; Ruff passed. Live OpenAPI documents 429 and 503.
- ID-03 is PASS. G1 remains PARTIAL: identity verification, membership/RBAC, invitations, opaque managed sessions, MFA and other matrix items remain open; release remains NO-GO.
- An earlier full `git diff --check` reports an extra blank line at EOF in the already-dirty `services/b2c/tests/test_orders.py`. That file was not changed in this rate-limit slice. Metadata records the blocker; scoped changed-file check is pending.
- Report: `docs/automation/seller_runs/2026-10-16/1116z-g1-id03-rate-limit-report.json`; metadata: `docs/automation/seller_runs/2026-10-16/1116z-g1-id03-rate-limit-metadata.json`.

### G1 inactive seller login denial вЂ” 2026-10-16 11:18 UTC

- Confirmed with a disposable PostgreSQL-backed inactive seller and correct credentials that the live B2B `/auth/login` returns 403. Deleted exactly one fixture row. Added a focused service test; 1/1 passed.
- ID-04 is PASS. During test fixture hashing, Passlib logged a trapped bcrypt version metadata warning (`bcrypt.__about__` absent); password verification still completed and returned the expected 403. Track the compatibility warning for dependency maintenance.
- G1 remains PARTIAL; release remains NO-GO. Report and metadata: `docs/automation/seller_runs/2026-10-16/1118z-g1-id04-inactive-login.json` and `docs/automation/seller_runs/2026-10-16/1118z-g1-id04-inactive-login-metadata.json`.

### G1 duplicate email conflict and race вЂ” 2026-10-16 11:27 UTC

- Normalized seller email before lookup/storage, added case-insensitive repository lookup and PostgreSQL unique `lower(email)` index (`0036_seller_email_ci`). Concurrent unique-index conflicts roll back and return 409.
- Applied migration locally. Live API checks: a case-variant duplicate after creation returned 409; two concurrent case-variant registrations returned exactly one 201 and one 409. Two disposable seller rows were removed. Unit tests: 4/4; Ruff and Alembic offline SQL passed.
- ID-02 is PASS. At this checkpoint ID-01 remained NOT_RUN because registration did not yet verify email and activated the seller; the later ID-01 implementation and evidence below supersede that checkpoint.
- Report and metadata: `docs/automation/seller_runs/2026-10-16/1127z-g1-id02-email-conflict.json` and `docs/automation/seller_runs/2026-10-16/1127z-g1-id02-email-conflict-metadata.json`.

### G1 new seller email verification вЂ” 2026-10-16 11:45 UTC

- New registrations now start in `PENDING_EMAIL`, receive a hashed, expiring one-time challenge via configurable SMTP, and move to `PENDING_REVIEW` only after consuming the token. Login stays denied through pending review; existing accounts were backfilled with verified status in migration `0037_seller_email_verify`.
- Added registration, confirmation, and resend screens/BFF routes. The confirmation token travels in the URL fragment and is removed from browser history before exchange.
- Real browser flow passed independently on desktop, tablet, and mobile: delivered email through local SMTP/Mailpit, pre-verification login denied, token accepted once, fragment removed, replay rejected (400), and pending-review login denied. Unit tests: 13 passed; Ruff passed. Exact disposable sellers and Mailpit messages were removed.
- ID-01 is PASS for the blueprint's email-verification requirement. Production SMTP and trusted legal-entity/KYB review activation were not exercised. G1 remains PARTIAL and release remains NO-GO.
- Report: `docs/automation/seller_runs/2026-10-16/1144z-g1-id01-email-verification-report.json`; metadata: `docs/automation/seller_runs/2026-10-16/1144z-g1-id01-email-verification-metadata.json`; three independent Playwright reports are linked there. Visual evidence: `docs/automation/evidence/seller-email-verified-{desktop-chromium,tablet-chromium,mobile-chromium}-2026-10-16.png`.

### G1 seller suspension and session revoke вЂ” 2026-10-16 11:51 UTC

- Added an internal admin-only B2B suspension operation. It changes the seller to `SUSPENDED`, disables login, and increments `session_version` atomically. Production requests pass through the existing signed admin-service-token verifier.
- Live local API flow passed: active seller login and `/auth/me` returned 200; suspension returned 200; the old session returned 401 and subsequent login returned 403. Missing service credentials returned 401; a nonexistent seller returned 404.
- PostgreSQL session integration tests passed: 2/2. Ruff passed. The exact temporary seller was deleted; no fixture rows remain. Passlib emitted the existing bcrypt metadata deprecation warning during fixture password hashing.
- ID-05 is PASS. Production signing/issuance of the admin service token was not exercised. G1 remains PARTIAL and release remains NO-GO.
- Report and metadata: `docs/automation/seller_runs/2026-10-16/1151z-g1-id05-suspension-report.json` and `docs/automation/seller_runs/2026-10-16/1151z-g1-id05-suspension-metadata.json`; live API contract: `docs/automation/evidence/b2b-openapi-id05-suspension-2026-10-16.json`.

### G1 cross-tenant resource isolation вЂ” 2026-10-16 11:56 UTC

- Added a live PostgreSQL + B2B integration test with two disposable sellers and seller-owned product, SKU, and order fixtures.
- The owner read each resource successfully. The second seller received 404 for the product and order; its stock adjustment against the foreign SKU also returned 404, leaving stock unchanged and creating no adjustment ledger entry.
- ID-09, ID-10, and ID-11 are PASS. Test result: 1 passed. Ruff passed. All fixture rows were removed; matching counts are zero.
- Report and metadata: `docs/automation/seller_runs/2026-10-16/1156z-g1-tenant-isolation-report.json` and `docs/automation/seller_runs/2026-10-16/1156z-g1-tenant-isolation-metadata.json`; API contract: `docs/automation/evidence/b2b-openapi-tenant-isolation-2026-10-16.json`.

### Identity membership foundation вЂ” 2026-10-16 12:01 UTC

- Added migration `0038_seller_memberships` with distinct seller login identities, tenant memberships and constrained roles (`OWNER`, `MANAGER`, `CATALOG_EDITOR`, `WAREHOUSE_OPERATOR`, `SUPPORT`, `FINANCE`, `VIEWER`), plus hash-only invitation storage with expiry and one-use state.
- Applied the migration locally. Backfill verification found 56 sellers, 56 corresponding users and 56 owner memberships, with no missing mappings. Ruff and Alembic offline SQL generation passed.
- This is schema groundwork only. Login has not yet been switched to membership context; invitation delivery/acceptance, role enforcement, tenant selection and team UI remain unimplemented. ID-06/07/08 and role requirements remain open in the matrix.
- Report and metadata: `docs/automation/seller_runs/2026-10-16/1201z-g1-identity-foundation-report.json` and `docs/automation/seller_runs/2026-10-16/1201z-g1-identity-foundation-metadata.json`.

### G1 seller invitations, acceptance and VIEWER authorization вЂ” 2026-10-16 12:21 UTC

- Added owner-only team listing/invitation APIs and Seller pages for team management and one-time invitation acceptance. Invitation tokens are stored as hashes, links carry the token in the URL fragment, and the accept screen clears the fragment before submission. Anonymous acceptance uses the same origin-checked, HMAC-backed CSRF mechanism with an anonymous session binding.
- Live local PostgreSQL/B2B/Mailpit integration passed: invitation delivery and 72-hour expiry, mismatched email rejection, expiry rejection, replay rejection, member login/context, and VIEWER product update denial (403). The exact temporary fixture rows and Mailpit messages were removed.
- Browser flow passed independently on desktop, tablet, and mobile: owner login, invite form, accept link, fragment removal, member login, and non-owner team access denial. Seller TypeScript and B2B Ruff passed.
- ID-06, ID-07, and ID-12 are PASS. ID-08 tenant selection/switching remains open; ID-13 payout route/policy and ID-14 live FINANCE product denial still require evidence. G1 remains PARTIAL and release NO-GO.
- Report and metadata: `docs/automation/seller_runs/2026-10-16/1220z-g1-team-invitations/report.json` and `metadata.json`; three independent Playwright reports and browser screenshots are linked there.

### G1 organization selection and tenant switching вЂ” 2026-10-16 12:36 UTC

- Login now requires an explicit organization when an identity has multiple active memberships. The global Seller tenant switcher lists eligible organizations and requests a new tenant-scoped token. The backend writes a durable audit record with source/target organizations and roles.
- Live PostgreSQL/B2B integration passed: organization selection, active membership validation, token scope after switching, rejection of non-member targets, and one persisted audit entry. Desktop, tablet, and mobile browser runs each passed 1/1; the browser flow selected an organization at login and switched tenants in the shared UI.
- ID-08 is PASS. Final browser evidence is in `docs/automation/seller_runs/2026-10-16/1236z-g1-tenant-switch/`; local disposable user rows left by earlier integration attempts were cleaned and verified absent. No production access was used.

### G1 FINANCE product mutation denial вЂ” 2026-10-16 12:21 UTC

- Extended the live invitation integration to add a FINANCE member and prove that product updates return HTTP 403. The final integration run passed, and the three independent invitation browser reports each contain 1 passed, 0 skipped, 0 unexpected tests.
- ID-14 is PASS. The invitation run report and metadata include the FINANCE authorization assertion.
- ID-13 remains NOT_RUN: the current backend has no seller payout lifecycle or payout route, so there is no implemented operation to verify for a WAREHOUSE_OPERATOR denial. No placeholder payout API was introduced. G1 and release remain NO-GO.
### G2 atomic product creation and idempotency вЂ” 2026-10-16 13:00 UTC

- Extended the Seller product browser flow to verify persisted product/SKU state after creation, replay the exact request, and reject reuse of the idempotency key with a changed payload. The checks use same-origin browser fetch so the actual HttpOnly seller session and CSRF boundary are present.
- Desktop, tablet, and mobile each passed independently (1 passed, 0 skipped, 0 unexpected). The flow observed HTTP 201 for atomic product plus one SKU, the same product/SKU IDs on read and retry, and HTTP 409 for a changed intent. Screenshots and raw Playwright JSON reports are stored under `docs/automation/`.
- ID PRD-01, PRD-05, and PRD-06 are PASS. The test cleanup soft-deletes its product; seven products created by failed diagnostic attempts were also soft-deleted, and the local active test-product count is zero. No production data was accessed.- Screenshot review found a literal question-mark placeholder for the Orders navigation entry. Replaced it with вЂњР—Р°РєР°Р·С‹вЂќ on all seven Seller pages that render the shared sidebar; reran all three product-creation viewports after the correction.
### G2 batch draft status — 2026-10-16 13:41 UTC

- PRD-02 now PASS: the local B2B API atomically persists 20 variants (contract limit 1–100), and rejects 101 variants and duplicate seller articles before creating records. Idempotent replay, 409 changed-intent conflict, persisted SKU fields, and three independent desktop/tablet/mobile browser runs passed.
- Run evidence: `docs/automation/seller_runs/2026-10-16/1344z-g2-product-draft-batch-final/`. Screenshots were inspected and the desktop logout controls were moved below page content to prevent overlap with Save.
- Seller media upload/quarantine/scanning remain unavailable; see DEF-PRD-09-001. PRD-09–12 remain NOT_RUN. Draft-created outbox delivery is also not wired to a compatible Admin consumer; PRD-13 remains NOT_RUN. Overall release remains NO-GO.

### G2 optimistic product revisions вЂ” 2026-10-16 13:16 UTC

- Corrected stale product and SKU `If-Match` responses from 409 to the contract-required 412. Product detail now returns the persisted revision and ETag; the Seller BFF forwards ETag and provides an origin-checked, CSRF-protected PUT route that requires `If-Match`.
- The live Seller browser flow accepted revision 1, persisted revision 2, rejected a second revision-1 update with HTTP 412, and read back the unchanged revision-2 description and ETag. Desktop/tablet/mobile each passed 1/1. Product edit unit suite passed 11/11 and Ruff passed.
- ID PRD-15 is PASS. The one product from a failed diagnostic browser assertion was soft-deleted; active atomic QA product count is zero.



- PRD-03 also PASS: a batch containing a negative price returns 422 and leaves no partial product or idempotency receipt; 9 local unit tests and the live PostgreSQL integration passed.

- PRD-04 PASS: a local fault proxy confirmed B2B committed the draft (201) and dropped the response; retrying the same idempotency key recovered the same product and operation IDs. This recovery test uses only disposable local fixtures.
- PRD-08 PASS: duplicate `seller_article` values differing only by case are rejected with 422 before any write; both schema and live database integration assertions pass.

### G3 inventory adjustment integrity — 2026-10-16 13:49 UTC

- Live B2B/PostgreSQL test passed receipt (+10), writeoff (-5), zero/oversized rejection, reserved-stock guard (409), same-key replay, same-seller cross-SKU conflict, cross-tenant key isolation, and ledger/on-hand reconciliation.
- INV-01–05, INV-08–11, and INV-13 are PASS. Evidence: `docs/automation/seller_runs/2026-10-16/1346z-g3-inventory-adjustments/`; the three authenticated browser reports also exercise stock adjustments.
- INV-12 lost-response status recovery remains NOT_RUN.
- INV-14 PASS: authenticated desktop/tablet/mobile browser runs showed the server-confirmed stock quantity after navigating to Inventory and reloading the page. The disposable product was soft-deleted after the check.
- INV-15 PASS: Inventory CSV export now quotes/escapes cells and prefixes formula-like text. Desktop/tablet/mobile browser checks downloaded the CSV containing malicious-looking test values and confirmed they were neutralized; screenshots and raw reports are under `docs/automation/seller_runs/2026-10-16/1354z-g3-inventory-csv-safety/`.
- INV-07 PASS: 50 simultaneous +1 requests all returned 200; the SKU reached exactly 53 from 3 and its persisted ledger sum was also 53. Evidence: `docs/automation/seller_runs/2026-10-16/1400z-g3-inventory-concurrency/`.
- INV-06 and INV-07 PASS: 50 concurrent +1 operations produced exactly 50 ledger entries; a reservation of 50 and writeoff of 4 raced on the same SKU, with one succeeding and one returning 409. Both serialization outcomes preserve `on_hand >= reserved` and ledger reconciliation. Evidence: `docs/automation/seller_runs/2026-10-16/1404z-g3-inventory-race/`.


### G3 inventory operation-status recovery — 2026-10-16 14:15 UTC

- INV-12 is PASS. B2B stores the ledger entry reference and exposes a seller-scoped GET by idempotency key. The Seller BFF forwards it with `no-store`; Inventory resolves a failed/ambiguous adjustment response against that status before reporting failure.
- The local PostgreSQL integration verified committed status, linked ledger ID, cross-seller isolation (404), and unknown-key behavior (404). The browser scenario committed the adjustment, replaced the upstream response with an ambiguous 503, recovered status in the UI, and verified quantity 10 after reload. Desktop, tablet, and mobile each passed independently (1 passed, 0 skipped, 0 unexpected).
- Evidence: `docs/automation/seller_runs/2026-10-16/1415z-g3-operation-status/`. Release remains NO-GO because DEF-PRD-09-001 and DEF-PRD-13-001 remain open.
### G2 category attribute validation — 2026-10-16 14:30 UTC

- PRD-07 is PASS. Category reads include a versioned attribute schema. Product draft creation validates required, numeric and select attributes and returns field paths; invalid drafts leave no product or operation receipt. The Seller form renders the selected schema and confirms before discarding entered attributes when the category changes.
- Live PostgreSQL integration passed (1/1). Desktop, tablet and mobile browser runs passed independently (1 passed, 0 skipped, 0 unexpected each), including checking the submitted attribute payload. Evidence: `docs/automation/seller_runs/2026-10-16/1430z-g2-category-attributes/`.
- The earlier progress entries saying TypeScript was unavailable are superseded: the Seller TypeScript check and production build now pass. Release remains NO-GO; open media and eventing blockers are unchanged.
### G2 legacy product PUT revision guard — 2026-10-16 14:45 UTC

- PRD-16 is PASS. The hidden legacy B2B `PUT /api/v1/products/{id}` alias rejects requests without `If-Match`, accepts the current revision, increments it, and returns 412 for a stale revision without changing the current description. Seller BFF desktop/tablet/mobile reports also cover current-revision success and stale 412.
- Live PostgreSQL test passed (1/1). Evidence: `docs/automation/seller_runs/2026-10-16/1445z-g2-legacy-put-revision/` plus the three independent browser reports in `1430z-g2-category-attributes/`.
### G1 payout role denial — 2026-10-16 15:00 UTC

- ID-13 is PASS. The payout command is guarded by `finance.manage`; a WAREHOUSE_OPERATOR gets 403. An authorized OWNER gets explicit 501 `FEATURE_NOT_CONFIGURED` because no payout provider or ledger is configured. The route creates no payout or financial record.
- Local live PostgreSQL/API integration passed 1/1 and cleaned all disposable identities. Evidence: `docs/automation/seller_runs/2026-10-16/1500z-g1-id13-payout-role/`. FIN-01 through FIN-13 remain NOT_RUN; release remains NO-GO.
### G2 hard-block public visibility — 2026-10-16 15:10 UTC

- PRD-18 is PASS. A local Admin hard-block event changed the product to terminal `HARD_BLOCKED`, set `is_active=false`, and made public product detail return 404. Before the event, the same endpoint returned 200.
- Live PostgreSQL/API integration passed (1/1); all disposable records were removed. Evidence: `docs/automation/seller_runs/2026-10-16/1510z-g2-hard-block-visibility/`. Release remains NO-GO due to remaining blueprint gates.
### G2 seller correction and resubmission — 2026-10-16 14:49 UTC

- PRD-14 is PASS. Field-level moderation reports are preserved in the canonical event and product response. Seller detail displays the blocking reason and reported path/code, then submits corrected values with `If-Match`; stale revisions reload and surface a conflict. The API increments the revision and transitions the product back to ON_MODERATION.
- Three independent authenticated browser reports passed desktop, tablet and mobile (1 passed, 0 failed, 0 skipped, 0 flaky each). The flow used local B2B and PostgreSQL persisted fixtures; product cleanup ran after each test. Evidence: `docs/automation/seller_runs/2026-10-16/1548z-g2-product-resubmit/`.
- Release remains NO-GO due to remaining blueprint gates.

### G2 immutable approved product snapshot — 2026-10-16 15:06 UTC

- PRD-17 is PASS. Migration `0043_product_published_snapshot` adds immutable revision records and a pointer to the published snapshot. Draft creation and revision-guarded seller updates persist content plus a SHA-256 hash. Moderation approval is bound to `reviewed_revision`, publishes that exact snapshot, and stale decisions receive 409. Public catalog/detail continue rendering the last approved content while a later edit is under review; hard-block visibility remains terminal.
- Live PostgreSQL integration passed and verified revisions 1 and 2, retained source text, and distinct hashes. Three independent authenticated browser reports passed desktop, tablet and mobile (1 passed, 0 failed, 0 skipped, 0 flaky each). Evidence: `docs/automation/seller_runs/2026-10-16/1504z-g2-published-snapshot-final/`.
- PRD-14 correction/resubmission remains covered by the same three reports. Release remains NO-GO due to remaining blueprint gates.

### G2 published snapshot final verification — 2026-10-16 15:15 UTC

- PRD-17 verification is complete against the rebuilt B2B service. Live PostgreSQL integration verified the immutable snapshot rows and stale moderation decision guard. Three independent authenticated Playwright reports passed desktop, tablet and mobile (1 passed, 0 failed, 0 skipped, 0 flaky each).
- PRD-14 resubmission is also included in this final run. Evidence: `docs/automation/seller_runs/2026-10-16/1511z-g2-published-snapshot-verified/`; integration output: `docs/automation/seller_runs/2026-10-16/1504z-g2-published-snapshot-final/integration.txt`.
- Release remains NO-GO; media, events, finance and security gates remain incomplete.

### G3 CSV inventory count import — 2026-10-16 15:35 UTC

- INV-17 and INV-18 are PASS. A seller-scoped import job records a SHA-256-bound CSV count preview with a 500-row ceiling, duplicate article rejection and per-row SKU/reservation errors. Preview leaves stock, revision, stock adjustments and inventory ledger unchanged. Commit rechecks the SKU revision and previous count, applies eligible rows and records ledger/adjustment receipts atomically. The same commit key returns the saved result without another write; another key gets 409.
- Seller page at `/imports` accepts UTF-8 `seller_article,on_hand` CSV, shows the dry-run diff and errors, stores only job/key references in session storage for recovery, and offers a new import after commit. Inventory now exposes seller articles for CSV preparation. The BFF target paths are described as proposed and mapped to the verified B2B routes in the typed target contract.
- Local PostgreSQL integration passed (1/1), including unchanged inventory on preview, partial rejection, committed stock/ledger reconciliation, replay and conflicting-key behavior. Three separate authenticated browser runs passed on desktop, tablet and mobile (1 passed, 0 skipped, 0 unexpected each). Ruff and Seller TypeScript check passed; Seller production build completed.
- Evidence: `docs/automation/seller_runs/2026-10-16/1535z-g3-inventory-import/`. Alembic is at `0044_inventory_import_jobs`. Overall release remains NO-GO; unrelated media, event-delivery, fulfillment, finance, security and visual gates remain open.

### G4 seller media intake and safe derivative — 2026-10-16 16:42 UTC

- PRD-09 through PRD-12 are PASS for local acceptance. Migrations `0045_seller_media_assets` and `0046_media_complete_queue` record seller-scoped idempotent upload intents, cascade with seller ownership, and ensure the scan queue starts only after explicit upload completion. BFF and B2B routes issue expiring HMAC upload capabilities, enforce 10 MB and SHA-256, isolate status by seller, and keep every asset private until READY. Draft creation accepts only READY assets owned by that seller and stores the approved URL in the product snapshot.
- A background worker scans the quarantine bytes with the local ClamAV daemon, checks actual image magic/type, bounds pixel count, decodes and re-encodes JPEG/PNG/WebP, applies EXIF orientation, strips metadata and serves public bytes only for READY assets. Unexpected scanner failures remain retryable; stale SCANNING records are recoverable. The UI now supports up to 20 files, upload recovery and scan status before saving the draft.
- Local PostgreSQL/B2B/ClamAV integration passed (1/1): scan does not start before completion, real EICAR detection, byte-digest mismatch, declared MIME versus JPEG magic mismatch, foreign-seller status/draft rejection, no public access for rejected media, and EXIF-free orientation-correct derivative. Seller image-to-draft browser flow passed in three independent runs: desktop, tablet and mobile each 1/1 with zero skipped/flaky/unexpected. Shared request middleware tests 5/5; Ruff, Seller TypeScript and production build passed. Alembic is `0046_media_complete_queue`.
- Evidence: `docs/automation/seller_runs/2026-10-17/1718z-g4-media/`.
- Production storage is still an open blocker: local acceptance uses a private Docker filesystem volume and local ClamAV. Managed object storage, replication, lifecycle/retention, production backup/restore and scanner operations remain unconfigured; defect `DEF-PRD-09-002` stays OPEN and seller GA remains NO-GO. No production data or deployment was used.

### G2 PRD-19 archive and order snapshot — 2026-10-16

- Added an owner-facing archive action to the product detail screen, with CSRF-protected same-origin DELETE, confirmation that existing orders keep their saved details, and return to the product list after acceptance.
- Live PostgreSQL/API integration passed: the seller archive endpoint returned 202; the product was soft-deleted; seller order detail retained the original `product_title`, `sku_name`, unit price, quantity and line total; disposable seller/product/SKU/order and outbox rows were removed.
- Independent browser runs passed on desktop, tablet and mobile (one test each; zero skipped, unexpected or flaky). Reports and integration record: `docs/automation/seller_runs/2026-10-17/1750z-g2-product-archive/`.
- Seller source TypeScript check passed. Production build was attempted, but Next.js failed prerendering `/404` with `<Html> should not be imported outside of pages/_document`; production build sign-off remains open and this does not count as verification of archive behavior.
- PRD-19 is PASS from persisted integration plus all three live browser runs. Overall release remains NO-GO; this slice does not close the remaining blueprint gates.

### G2 PRD-13 product event outbox duplicate delivery — 2026-10-16 17:00 UTC

- PRD-13 is PASS for the required product event delivery scenario. B2B now maps product events onto the canonical versioned Admin event envelope and accepts only successful consumer responses; arbitrary HTTP 409 is no longer mistaken for duplicate success.
- Live local PostgreSQL integration passed (1/1): Admin committed the event, the first acknowledgement was lost, B2B retried from its persisted outbox, and the producer reached SENT on attempt 2. Admin retained exactly one processed event and one moderation ticket. The isolated producer database and disposable event fixtures were removed; the append-only Admin audit receipt remains by design.
- Evidence: `docs/automation/seller_runs/2026-10-16/1700z-g2-prd13-outbox/`. This is a backend-only requirement; no UI behavior is inferred from this run. No production data or deployment was used.
- G2 still has other open requirements; overall release remains NO-GO.

### G4 allocation authorization and idempotent receipt — 2026-10-16 17:29 UTC

- ORD-04 and ORD-05 are PASS. Seller order detail now offers a receipt confirmation that persists `seller_accepted_at` and increments the allocation revision once. Repeat and concurrent requests serialize on the allocation row and return the existing accepted state. The operation does not alter payment status, stock or shipping state.
- Added `orders.fulfill` for OWNER, MANAGER and WAREHOUSE_OPERATOR. SUPPORT may read orders but cannot accept. Allocation queries remain tenant-scoped and conceal another seller’s allocation with 404.
- Local PostgreSQL/API integration passed (1/1). Three separate browser reports passed desktop, tablet and mobile (one expected, zero skipped, unexpected or flaky each); browser API responses were stubbed, and persistence/authorization were separately asserted against the live local API/database. TypeScript and Ruff passed.
- Evidence: `docs/automation/seller_runs/2026-10-16/1729z-g4-order-receipt/`. G4 packing, shipping, carrier reconciliation, delivery and returns remain open; release remains NO-GO.
- The same integration also closes ORD-03: the persisted seller API response exposes only allocation and seller line snapshot fields; buyer order identity and delivery PII are absent. Evidence remains in `docs/automation/seller_runs/2026-10-16/1729z-g4-order-receipt/`.

### Seller production build follow-up — 2026-10-16 17:36 UTC

- The earlier `/404` and `/500` `<Html>` prerender failure did not reproduce in two clean isolated production builds. The latest run passed compile, type/lint checks, 25/25 static page generation, trace collection and route output, including Seller order detail.
- Builds used separate ignored `distDir` outputs to preserve the local preview. Next.js temporarily modified `tsconfig.json`; that change was reverted after each run. The exact cause of the earlier build-state failure is not confirmed.
- Evidence: `docs/automation/seller_runs/2026-10-16/1733z-seller-production-build/`. No production data or deployment was used.

### G4 partial packing manifests and allocated-quantity bound — 2026-10-16 18:04 UTC

- ORD-06 and ORD-07 are PASS. Added durable seller packing manifests with per-allocation idempotency, canonical request hashes and an allocation row lock. Multiple partial parcels are supported; cumulative packed quantity cannot exceed each seller order line. Same-key retries return the original manifest, changed payload returns 409, and overpacking returns 409. The manifest and revision update commit together.
- Seller order detail now exposes remaining packable quantities, saved parcels and recovery after an ambiguous response. The same key is reused for the same payload after a transient failure. `PACKED` is clearly presented as a local parcel manifest; it does not imply carrier selection, label creation, tracking, dispatch or delivery.
- Live PostgreSQL/B2B integration passed (1/1); three independent browser runs passed desktop/tablet/mobile (one expected, zero skipped/unexpected/flaky each). TypeScript, Ruff and isolated production build passed. Evidence: `docs/automation/seller_runs/2026-10-16/1736z-g4-order-packing/` and `docs/automation/seller_runs/2026-10-16/1759z-seller-packing-build/`.
- G4 carrier, dispatch, delivery and returns requirements remain open; overall release remains NO-GO.

### G4 local carrier label idempotency and timeout reconciliation — 2026-10-16 18:23 UTC

- ORD-08 and ORD-09 are PASS for the local test flow. Migration `0049_carrier_ops` adds one seller-scoped carrier operation per packed parcel and a unique durable local simulator label. The simulator uses deterministic `SIM-...` references and is allowed only in local/dev/test/development environments; staging and production are denied.
- Live PostgreSQL/B2B integration passed (1/1): the simulator committed a label and the test dropped its acknowledgement; the operation remained `PENDING_PROVIDER`; a status read reconciled via same-key retry to `LABEL_CREATED`; repeat used the same label, a different key conflicted, and the persisted label count stayed one. Fixtures were cleaned.
- Three separate browser runs passed desktop, tablet and mobile (one expected each; zero skipped, unexpected or flaky). The UI displays the local test label and explicitly states that no real carrier transmission occurred. Browser API routes were stubbed; persistence was proven by the independent integration test. Evidence: `docs/automation/seller_runs/2026-10-16/1810z-g4-carrier-reconciliation/`.
- Seller TypeScript passed. An isolated production build attempt still fails during Next.js `/500` prerender with `<Html> should not be imported outside of pages/_document`; build is not counted as PASS. No real provider was selected. Actual provider dispatch, signed delivery callbacks, cancellation/returns and other G4 requirements remain open; overall release remains NO-GO.

### G4 buyer cancellation blocks Seller packing — 2026-10-16 18:39 UTC

- ORD-10 is PASS for the local cancellation flow. Buyer `CANCEL_PENDING` now writes a PII-free `seller_order.cancelled.v1` event to the transactional B2C seller outbox. The existing retry worker routes it to an idempotent, service-authenticated B2B consumer. B2B locks the seller allocation, records `CANCELLED`, and rejects new packing and carrier operations. Seller order detail disables pack/label actions and explains the cancellation.
- B2C PostgreSQL outbox persistence passed (1/1), live B2C-to-B2B delivery passed (1/1), B2B cancellation replay and packing conflict passed (1/1), and the B2C order unit suite passed 49/49. Three independent Playwright runs each passed two scenarios (desktop/tablet/mobile; zero skipped, unexpected or flaky). Browser endpoints were stubbed; persistence was separately verified. Evidence: `docs/automation/seller_runs/2026-10-16/1823z-g4-cancel-packing/`.
- Cancellation propagation is asynchronous; projections may briefly differ until the outbox is consumed. No production/provider work was performed. ORD-11 through ORD-17 and the remaining release gates are open; overall release remains NO-GO.

### G4 signed carrier events and out-of-order reconciliation — 2026-10-16 18:47 UTC

- ORD-11 and ORD-12 are PASS for the local test adapter. Migration `0050_carrier_webhooks` adds revisioned shipment lifecycle state and durable event receipts. A local-only HMAC-SHA256 endpoint rejects unsigned traffic; event payloads are tenant/parcel scoped, tied to the existing LOCAL_TEST label operation, deduplicated by event ID and revision, and applied in sequence. A delivery event received before dispatch remains pending until its predecessor arrives; replay with changed content conflicts.
- Live PostgreSQL/B2B integration passed (1/1): invalid signature 401, delivery revision 2 pending, dispatch revision 1 then delivery revision 2 applied to DELIVERED, same event replay stable, changed payload replay 409, no pending receipts left, all fixtures cleaned. Three separate browser runs passed three scenarios each (desktop/tablet/mobile; zero skipped, unexpected or flaky). Evidence: `docs/automation/seller_runs/2026-10-16/1840z-g4-carrier-webhooks/`.
- Seller TypeScript passed. The Seller detail displays the persisted shipment status. Only LOCAL_TEST signatures were exercised; actual provider signature formats and downstream events remain unverified. ORD-13 through ORD-17 and other release gates remain open; overall release remains NO-GO.

### G4 seller suspension preserves buyer order — 2026-10-16 18:52 UTC

- ORD-13 is PASS for persisted order isolation. A live local B2C+B2B PostgreSQL integration suspended and deactivated the seller associated with a paid buyer order. The buyer order status and saved line remained unchanged, and suspension did not queue a cancellation event. Fixtures were cleaned. Evidence: `docs/automation/seller_runs/2026-10-16/1852z-g4-seller-suspension/`.
- No Seller UI code changed. A separate exploratory buyer-detail browser probe was blocked by a 500 from the temporary local storefront Next.js dev server; that probe is not counted as acceptance evidence and no UI claim is made. ORD-14 through ORD-17 and other release gates remain open; overall release remains NO-GO.

### G4 return policy blocker and outage alerting gap ? 2026-10-16 18:55 UTC

- ORD-14, ORD-15 and ORD-16 are BLOCKED by approved-spec decisions S-15, PR-003 and PR-004: merchant of record, delivery/return responsibility and refund/payout rules are unresolved. No return behavior was invented or tested. Evidence: `docs/automation/seller_runs/2026-10-16/1855z-g4-returns-blocked/`.
- ORD-17 is PARTIAL: the local carrier test already proves a committed label can remain pending after a lost acknowledgement and reconcile on retry (ORD-09 evidence). No alert delivery, escalation owner or provider outage contract is configured or verified. G4 and release remain NO-GO.

### G6 Seller order permission-based actions ? 2026-10-16 19:13 UTC

- UI-13 is PASS. B2B now exposes the current tenant role and effective permissions; Seller order detail only renders accept/packing/dispatch actions when the server response includes `orders.fulfill`, and hides them if permission lookup is unavailable. B2B still enforces the same permission on every mutation.
- Live local API/PostgreSQL integration passed (1/1): OWNER had `orders.fulfill`, SUPPORT did not, SUPPORT remained read-only and received 403 for fulfillment. The same test persisted acceptance and packing and cleaned its fixtures. B2B permission tests passed 8/8.
- Three separate browser runs each passed five scenarios (desktop/tablet/mobile; zero skipped, unexpected or flaky); TypeScript and Ruff passed. Browser API routes were stubbed, with live role and persistence checks recorded separately. Evidence: `docs/automation/seller_runs/2026-10-16/1911z-g6-ui13-permissions/`.
- The live run exposed a lazy-loading `MissingGreenlet` on the newly packed shipment response; the service now eagerly loads or explicitly initializes `carrier_operation`. Re-running the live integration passed. Other G6 and release requirements remain open; overall release remains NO-GO.

### G4 one-seller and multi-seller checkout allocations ? 2026-10-16 19:19 UTC

- ORD-01 and ORD-02 are PASS. Two live local PostgreSQL cases executed the actual B2C checkout and persisted the buyer order and PII-minimized seller outbox. The single-seller case produced one allocation; the two-seller case produced one allocation per seller.
- Both outbox envelopes were sent to the real local B2B allocation endpoint and persisted as seller orders with inbox receipts; the B2C outbox rows reached SENT. All fixtures were verified removed from both databases. Inventory snapshot/reservation calls were isolated behind a deterministic local test double; no payment or shipping provider was selected. Evidence: `docs/automation/seller_runs/2026-10-16/1917z-g4-order-allocation/`.
- G4 returns remain blocked by S-15/PR-003/PR-004; G4 alerting is partial and the broader Seller release remains NO-GO.

### G6 keyboard focus for seller sign-in and navigation — 2026-10-18

- UI-06 is PARTIAL. Added a consistent 3px cobalt focus outline for Seller Hub controls and skip links after browser traversal found missing indicators on the global skip link and seller sidebar navigation.
- Three independent Playwright runs passed on desktop, tablet and mobile: each verified keyboard order and visible focus for the sign-in form and dashboard navigation (2/2 expected, 0 unexpected, skipped or flaky per run).
- Product, inventory, order, moderation, team and modal workflows still need keyboard traversal evidence before UI-06 can pass. Evidence: `docs/automation/seller_runs/2026-10-18/keyboard-focus/`.

### G6 expanded keyboard focus traversal — 2026-10-18 14:22 UTC

- Tightened the Seller keyboard E2E so the six route checks fail if the visible-control count exceeds the verified cap or if Tab does not reach every visible keyboard-operable control. Each focused control must have `:focus-visible`, a 3px solid outline, and remain visible in the viewport.
- Three independent Playwright project runs passed after the assertion change: desktop, tablet and mobile each **3 passed, 0 failed, 0 skipped, 0 flaky**. Covered sign-in, dashboard navigation, and all visible controls on `/products/new`, `/inventory`, `/orders`, `/moderation`, `/team`, and `/finance`.
- Per-route focus JSON and screenshots are in `docs/automation/evidence/seller-keyboard-{products-new,inventory,orders,moderation,team,finance}-{desktop,tablet,mobile}-chromium-2026-10-18.*`. Final independent reports and run metadata are in `docs/automation/seller_runs/2026-10-18/keyboard-focus-expanded/`.
- UI-06 remains **PARTIAL**: this run does not cover every Seller route, modal/dialog workflows, or a full screen-reader review. No gate or release readiness is inferred from this focused run.

### G6 WCAG 2.2 axe accessibility audit — 2026-10-18

- UI-07 is PARTIAL. Added an axe-core 4.14.0 Playwright audit for 17 reachable public/authenticated Seller screens and ran independent desktop, tablet and mobile Chromium projects. Each final report is 1 passed, 0 failed, 0 skipped, 0 flaky; each axe scan has zero violations.
- Fixed the dashboard SKU select button name mismatch and keyboard access to horizontally scrollable tables. Added focusable table wrappers and visible focus indication.
- The audit does not cover `/orders/{id}` because the local B2B database has no seller order; no fake order was created. Manual assistive-technology review remains outstanding. Full UI-07 remains PARTIAL. Reports, metadata and browser evidence: `docs/automation/seller_runs/2026-10-18/axe-accessibility/` and `docs/automation/evidence/seller-axe-*-2026-10-18.json`.

### Commercial flows remain disabled pending ADR — 2026-10-18

- Per the user’s explicit decision, keep merchant-of-record/tax/receipt, delivery/returns, refund/restock, PSP/commission and settlement flows disabled until the relevant ADRs are approved. No responsibility, provider, fee or accounting rule has been inferred.
- ORD-14, ORD-15 and ORD-16 remain BLOCKED. Finance/payout screens remain unavailable. Any LOCAL_TEST carrier behavior is a test harness only and does not establish a production delivery contract. Decision record: `docs/automation/seller_runs/2026-10-18/axe-accessibility/commercial-flow-decision.md`.

### G6 UI-09 initial wizard recovery follow-up — 2026-10-18

- `/products/new` now saves a tenant-scoped local recovery draft after a 900 ms debounce before the first atomic create request. Same-tab reload restores text fields and SKU inputs; media files require reselection. A simulated 503 retained the form and idempotent create state. The test also verified `19.99` becomes 1999 minor units, beforeunload protection, and logout cancel/confirm behavior.
- Separate desktop, tablet and mobile Chromium reports each passed **2 passed, 0 failed, 0 skipped, 0 flaky**; Seller typecheck passed. Evidence and reports are in `docs/automation/seller_runs/2026-10-18/ui-09-draft-autosave/`.
- UI-09 remains **PARTIAL**: the initial form recovery is limited to the current browser tab's `sessionStorage`; it is not a persisted service draft and has no verified operation lookup for an unknown create result. The earlier live PostgreSQL integration verifies the separate blocked-product revision and outbox behavior.

### G6 UI-08 state truthfulness follow-up — 2026-10-18

- Added six browser scenarios for product-list loading/empty, orders error/retry, moderation empty, product-detail error, order-detail error, and a packed shipment state. The shipment check confirms the localized quantity, verifies packing controls do not overlap, and confirms that `PACKED` does not imply carrier delivery.
- Independent desktop, tablet and mobile runs each passed **6 passed, 0 failed, 0 skipped, 0 flaky**. Per-state screenshots and Playwright JSON, quality and metadata reports are stored in `docs/automation/seller_runs/2026-10-18/ui-08-state-truthfulness/`. Seller typecheck passed.
- UI-08 remains **PARTIAL**: this is focused route-state coverage with deterministic browser API stubs. Other Seller screens/state combinations and the wider typed BFF/RFC7807 error contract remain unverified.

### G6 blocked-product correction autosave and revision conflict — 2026-10-18

- UI-09 is PARTIAL. Blocked-product correction forms now autosave title, description and characteristics after a 900 ms debounce using the current If-Match revision. B2B persists the correction without leaving BLOCKED or creating a moderation event; explicit PUT remains the submit-for-review action. A stale revision opens a modal conflict dialog with server reload or deliberate local rebase, and unsaved changes trigger a beforeunload warning.
- Live B2B/PostgreSQL integration passed (1/1): persisted autosave revision, stale 412 did not overwrite, no moderation outbox event on autosave, explicit submission generated exactly one moderation event. Fixtures are cleaned in `finally`; output: `docs/automation/seller_runs/2026-10-18/ui-09-draft-autosave/integration-output.txt`.
- Three separate browser runs passed on desktop/tablet/mobile (each 1 passed, 0 failed, skipped or flaky). They verify edits survive 412, focus cycles inside the dialog, axe reports zero dialog violations, rebase saves the local edits against the latest revision, and autosave does not submit for moderation.
- UI-09 remains PARTIAL because `/products/new` does not autosave before the initial atomic POST. Traces, reports and screenshots: `docs/automation/seller_runs/2026-10-18/ui-09-draft-autosave/` and `docs/automation/evidence/seller-ui09-*`.

### G6 Seller media upload progress and failed scan ? 2026-10-18

- UI-10 is PASS for the local Seller/B2B flow. Upload now exposes per-file accessible transfer progress, then a security-scanning state, verified completion, or a filename-specific scan rejection. A rejected media file blocks the atomic product draft request.
- Three independent Playwright runs passed desktop, tablet and mobile (each 2 passed, 0 failed, skipped or flaky). The success case used the local Seller/B2B/PostgreSQL pipeline; the rejected UI state was routed deterministically and asserted that no draft POST occurred. A separate live local B2B/PostgreSQL/ClamAV integration passed 1/1 and verified MALWARE_DETECTED, non-public rejected media, ownership isolation and safe derivatives.
- Reports and metadata: `docs/automation/seller_runs/2026-10-18/ui-10-media-upload/`. Managed storage durability and production scanner operations remain open under DEF-PRD-09-002; no production readiness is inferred. Commercial flows remain disabled pending ADR.

### G6 Seller stock adjustment timeout recovery ? 2026-10-18

- UI-11 is PASS. Stock adjustment recovery now validates the status response body (`COMMITTED`, matching SKU and delta, consistent on-hand/reserved/available values, and ledger reference) before showing success. An unknown or unavailable status keeps the original idempotency key and leaves the SKU form available for retry. Fixed false success and hidden-form defects as `DEF-UI-11-001`.
- Three independent Playwright runs passed desktop, tablet and mobile (each 2 passed, 0 failed, skipped or flaky). The live scenario committed through local BFF/B2B/PostgreSQL, dropped the BFF acknowledgement, recovered from status GET, verified a single submission and compensated the stock back to its original value. A second scenario returned PENDING and verified no success claim plus same-key retry. Screenshots, reports and metadata: `docs/automation/seller_runs/2026-10-18/ui-11-timeout-recovery/`.
- No production environment or data was used. Other Seller requirements and overall release gates remain open.

### G6 Seller moderation history — 2026-10-18

- UI-12 is PASS. Canonical moderation decisions are persisted with event/action, resulting state, reviewed revision, actor/ticket, reason, comments, field reports, and occurrence time. Added an owner-scoped B2B history route, authenticated no-store Seller BFF proxy, and read-only expandable decision timeline. Resolved DEF-UI-12-001.
- Three independent Playwright reports passed desktop, tablet, and mobile (each 1 passed, 0 failed/skipped/flaky). The local browser integration applied approval and block events and asserted API history plus visible field-level feedback. Backend moderation unit tests: 27 passed; Seller TypeScript check passed; local database migration 0052 applied.
- Evidence: `docs/automation/seller_runs/2026-10-18/ui-12-moderation-timeline/`. No production data or systems used. Commercial flows remain disabled pending ADR; overall Seller requirements and release gates remain open.


### G6 Seller responsive navigation and 390px/768px layouts ? 2026-10-18

- UI-04 and UI-05 are PARTIAL. Added a keyboard-operable mobile navigation drawer and corrected narrow-width layout defects in Seller forms, headings, search controls, order empty state, and dashboard sign-out controls.
- Three independent Chromium Playwright projects passed. Each checked nine authenticated Seller routes at 390px and 768px, validated no document overflow, and exercised drawer visibility, Escape close, active navigation, and focus return. Each report: 1 expected, 0 unexpected, skipped, or flaky. TypeScript check passed.
- Evidence and review candidate screenshots: `docs/automation/seller_runs/2026-10-18/ui-04-05-responsive-candidate/`. Data came from the local Seller BFF/B2B/PostgreSQL QA environment. At the time of this run UI-04/05 were PARTIAL pending owner approval; the product owner approved the 390px/768px dashboard and product-create captures on 2026-10-19 (see G6 approval entry below). UI-14 was subsequently completed and is PASS.
- No production systems or data were used. Commercial flows remain disabled pending ADR.


### G6 responsive-width and browser error audit ? 2026-10-18

- UI-14 is PASS: three independent Chromium projects covered all nine Seller routes at 320, 390, 768, 1024, 1280, and 1440 CSS pixels (54 route/viewport observations per run). No document overflow, broken image elements, unexpected page errors, or unexpected console errors were found.
- Four or four or five 501 console messages per run were paired with the local `/api/seller/finance/overview` response, whose verified body reports `FEATURE_NOT_CONFIGURED`; finance remains intentionally disabled pending ADR.
- The 320px audit found a moderation decision card overflowing its container. Constrained the card and heading layout; all three final reports passed. Resolved DEF-UI-14-001. TypeScript check passed.
- UI-04 and UI-05 remain PARTIAL because approved responsive visual baselines are absent; their candidate screenshots still need owner approval. Evidence: `docs/automation/seller_runs/2026-10-18/ui-04-05-responsive-candidate/`. No production systems or data were used.


### G6 Seller UI-08 expanded state truthfulness ? 2026-10-18

- Expanded state checks from six to nine scenarios, adding dashboard loading/error without false zero totals, inventory empty response, and SKU failure handling.
- Three independent Chromium runs passed on desktop, tablet and mobile: each **9 passed, 0 failed, 0 skipped, 0 flaky**. Seller typecheck passed. Reports and metadata are in `docs/automation/seller_runs/2026-10-18/ui-08-state-truthfulness/*-expanded.*`.
- UI-08 remains PARTIAL: responses were deterministic browser stubs; other Seller screens/state combinations and the typed BFF/RFC7807 contract remain open. Commercial flows remain disabled pending ADR.


### G3 INV-16 100k SKU cursor and aggregation ? 2026-10-18

- Added a PostgreSQL scale regression test that creates only transaction-scoped temporary fixtures, traverses 100,000 SKUs in 1,000 pages of 100, validates every keyset row and signed cursor, and checks exact aggregate totals.
- Local Docker Compose PostgreSQL result: **1 passed**; 2,751,989-byte Python traced peak during pagination; 40.039 seconds with tracing; no persistent fixture rows. Existing browser coverage separately verifies BFF cursor paging and dashboard/API parity.
- INV-16 is PASS for its stated 100k no-truncation criterion. This focused result does not imply full Seller readiness; the wider S-10 product/export risk and all other matrix gates remain independently tracked. Evidence: `docs/automation/seller_runs/2026-10-18/inv-16-100k/`.


### G6 UI-04/UI-05 responsive baseline owner approval ? 2026-10-19

- Product owner approved dashboard and product-create screenshots at 390 CSS px and 768 CSS px. Copied the four candidate captures into `docs/design-system/baselines/seller-responsive-approved-2026-10-18/` and recorded SHA-256 hashes and approval scope in `approval.json`.
- UI-04 and UI-05 are PASS for the approved responsive baseline scope; the three independent responsive Playwright reports already show all required route/viewport checks passing. UI-03 desktop Stitch parity and full Seller release remain open.


### G3 S-10 bounded asynchronous inventory export ? 2026-10-18

- Replaced client-current-page CSV with idempotent asynchronous PostgreSQL export, a 100,000-row hard cap, formula-safe cells, SHA-256, seller-bound signed downloads, and 15-minute artifact expiry/cleanup. Added Redis fail-closed per-seller rate limiting (5 requests/hour).
- Added lease-generation fencing after finding a stale worker could overwrite a newer artifact. Local PostgreSQL regression: 6 passed; live Seller BFF?B2B?PostgreSQL integration: 1 passed. Three independent browser projects each passed 2/2. Ruff passed.
- S-10 is RESOLVED for bounded export behavior. Job metadata currently has no purge policy; note this limit in the run report. This does not close the Seller release gate.
- Evidence: `docs/automation/seller_runs/2026-10-18/inventory-export/` and `.../inventory-export-ui/`.


### G7 SEC-13 bounded inventory export scale ? 2026-10-18

- Added PostgreSQL regression using 10,000 temporary products and 100,000 temporary SKUs. The export worker streamed all rows into an 11,066,817-byte CSV in 9.556 seconds; SHA-256 matched the job record; Python `tracemalloc` peak was 1,907,860 bytes. Test passed and fixtures were transaction-local.
- SEC-13 is PASS for the 100k inventory CSV criterion. This heap measurement does not claim full container RSS. SEC-11, SEC-12, and SEC-14 remain NOT_RUN. Evidence: `docs/automation/seller_runs/2026-10-18/sec-13-export-scale/`.


### G4 Seller commercial operations disabled until ADR — 2026-10-19

- Following the product owner's decision to keep commercial flows disabled, removed Seller UI controls for order acceptance, packing and dispatch. The order detail now explains that acceptance, packing, dispatch, returns, refund/restock and settlement are unavailable pending ADRs; existing carrier simulator records are visibly test-only. The order detail, Finance unavailable, email verification/resend, login, registration and logout screens use the shared typed API client; malformed success payloads are rejected and nested B2B feature codes are preserved.
- Seller BFF and B2B API independently return HTTP 503 `COMMERCIAL_FLOW_DISABLED` for acceptance, packing manifests and dispatch. Browser tests confirmed the BFF rejects all three before any upstream request. Backend order/finance unit tests passed 6/6. TypeScript passed; three independent desktop/tablet/mobile reports each passed 17/17 with no skipped, failed or flaky tests.
- The PostgreSQL-backed no-mutation integrations are updated but skipped in this run because local PostgreSQL/B2B test URLs are not configured. Run them against isolated QA services before claiming persistence-level verification.
- ORD-14/15/16 and G4 commercial behavior remain BLOCKED until merchant-of-record/tax, delivery/returns responsibility, refund/restock, and PSP/fees/settlement ADRs are approved. Overall Seller release remains NO-GO. Current direct Seller UI scan finds 0 `fetch()` calls across 0 UI files. Evidence: `docs/automation/seller_runs/2026-10-19/commercial-flows-disabled/`.

### G2 UI-09 server operation recovery — 2026-10-19

- Added a seller-scoped idempotency receipt lookup for atomic product drafts and wired the typed BFF recovery route. The new-product form now reconciles a retained mutation key with the server after reload and links to the recovered product.
- Backend product creation tests: 5 passed; Seller TypeScript passed; desktop/tablet/mobile Chromium recovery: 1/1 each. Pre-create field contents still rely on tenant-scoped sessionStorage until the atomic create succeeds, so UI-09 remains PARTIAL. Evidence: docs/automation/seller_runs/2026-10-19/ui-09-server-recovery/.

### G1 opaque Seller sessions — 2026-10-19

- Replaced the browser's raw JWT cookie flow with a BFF exchange to a short-lived opaque server session. Added seller_sessions with hashed token, tenant/user scope, session-version fencing, expiry, device metadata and revocation; refresh rotates the session record within its family, and logout/logout-all invalidate records.
- Auth backend tests 15/15, full B2B suite 272 passed/33 skipped, Seller TypeScript and Ruff passed. A deterministic local B2B boundary plus Next Seller proved opaque cookie, refresh rotation, session lookup and revocation across desktop/tablet/mobile (1/1 each). ID-16 remains PARTIAL only because bank-change step-up MFA is not in scope while finance is disabled pending ADR. Evidence: docs/automation/seller_runs/2026-10-19/opaque-session/.

### G2 UI-09 server autosave - 2026-10-19

- Added seller-owned `seller_draft_autosaves` with bounded payload schema, 30-day expiry and optimistic revision fencing. `/products/new` retains only a local pointer/media names while authoritative pre-create fields autosave through the typed BFF; a lost atomic-create response first checks the operation receipt, then restores the server draft. Successful atomic create removes the autosave; ambiguous writes retain it.
- Backend autosave tests: 3 passed; Alembic 0064 offline SQL passed; Seller TypeScript passed. Real Next BFF boundary plus local B2B mock passed autosave PUT/GET/DELETE, stale revision 412 and CSRF checks; desktop/tablet/mobile each passed 3/3. PostgreSQL persistence integration remains unconfigured, so UI-09 stays PARTIAL. Evidence: docs/automation/seller_runs/2026-10-19/ui-09-server-autosave/.

- SEC-11 restore drill - 2026-10-19: isolated local PostgreSQL dump/restore across B2C, B2B and Admin matched counts and order-independent row checksums; Admin audit-chain hashes, links and head remained valid. SEC-11 is PARTIAL because offsite WAL/PITR RPO/RTO evidence is not configured. Evidence: docs/automation/seller_runs/2026-10-19/sec-11-restore/.
- SEC-12 outbox recovery - 2026-10-19: persisted reservation outbox retry after downstream B2C recovery passed 2 targeted tests. SEC-12 is PARTIAL because a deterministic worker crash after DB commit and before publish was not injected. Evidence: docs/automation/seller_runs/2026-10-19/sec-12-outbox-recovery/.

- SEC-14 exposure scan - 2026-10-19: production/staging Compose checks confirmed only the gateway publishes a host port and the dedicated recovery worker remains private. Runtime DB outage plus PSP/carrier drills are not run; SEC-14 is PARTIAL. Evidence: docs/automation/seller_runs/2026-10-19/sec-14-exposure-outage/.

- UI-09 closure - 2026-10-19: isolated PostgreSQL database migrated through 0064; live autosave integration passed 1/1 for persisted revision, reload, stale 412 and delete. With the three-project browser run at 3/3 each, UI-09 is now PASS. Evidence: docs/automation/seller_runs/2026-10-19/ui-09-server-autosave/.

- SEC-12 closure - 2026-10-19: live isolated PostgreSQL crash boundary passed. A subprocess claimed and committed an outbox lease, exited with code 23 before publish, and a fresh worker recovered the expired lease and delivered exactly once; persisted retry tests also passed. SEC-12 is now PASS. Evidence: docs/automation/seller_runs/2026-10-19/sec-12-outbox-recovery/.

- S-11 client cleanup - 2026-10-19: ProductCreate category retry and tenant switching now refresh through typed client state/router refresh; no inline fetch(), response.json(), or window.location.reload() remains in Seller page source.

- S-11 tenant retry verification - 2026-10-19: after replacing full-page reload with router/state refresh, tenant switching passed 1/1 on desktop, tablet and mobile; ProductCreate category retry remains local and typed. Reports: docs/automation/seller_runs/2026-10-19/s11-tenant-switch-client/playwright-current-{desktop,tablet,mobile}-chromium.json.

- Current B2B regression after UI-09/SEC-12 and S-11 client changes: uv run pytest -q passed 275, skipped 37, failed 0; Ruff and Seller TypeScript passed. Two existing warnings remain.

- UI-07 order-detail coverage - 2026-10-19: deterministic typed-BFF allocation fixture passed axe-core WCAG checks on desktop/tablet/mobile 1/1 each with zero violations. UI-07 remains PARTIAL only for manual assistive-technology review. Evidence: docs/automation/seller_runs/2026-10-19/ui-07-order-detail-axe/.

- SEC-14 runtime DB outage - 2026-10-19: rebuilt B2B with bounded asyncpg connect timeout; local PostgreSQL stop/restart drill returned `/ready` 200 -> 503 `NOT_READY` -> 200. SEC-14 remains PARTIAL only for PSP/carrier drills blocked by ADR. Evidence: docs/automation/seller_runs/2026-10-19/sec-14-exposure-outage/runtime-db-outage.json.

### G6 UI-08 state truthfulness refresh — 2026-10-19

- Re-ran the nine state scenarios independently on desktop, tablet and mobile Chromium after aligning the packed-shipment assertion with the ADR-disabled read-only order detail. Each project passed **9/9, 0 failed, 0 skipped, 0 flaky**; 33 fresh screenshots were captured.
- The fixture verifies loading, empty, retryable failures, dashboard metrics failure, inventory/SKU failure, and a saved shipment quantity without exposing packing/dispatch controls or implying carrier delivery.
- UI-08 remains **PARTIAL**: responses are deterministic browser route stubs, the full Seller state matrix is not covered, and the typed BFF/RFC7807 contract remains open under S-11. Evidence: `docs/automation/seller_runs/2026-10-19/ui-08-state-truthfulness/`.

### G6 UI-06 keyboard/focus route expansion — 2026-10-19

- Expanded browser traversal from six to thirteen authenticated Seller routes: dashboard, products, new product, product detail, SKU list, inventory, imports, orders, order detail, moderation, team, finance and payouts.
- Added explicit responsive navigation-drawer opening on tablet/mobile and verified `aria-expanded=true` before walking navigation links. Three independent Chromium projects passed **3/3, 0 failed, 0 skipped, 0 flaky**; 45 route/focus screenshots and JSON observations were captured.
- UI-06 remains **PARTIAL** because full screen-reader review and additional modal/dialog workflows are still outside this browser-only check. Evidence: `docs/automation/seller_runs/2026-10-19/ui-06-keyboard-focus/`.

### G6 UI-08 state matrix expansion — 2026-10-19

- Added three deterministic browser scenarios for finance provider absence, team member API failure and inventory import failure. Each keeps a dependency failure explicit and avoids rendering fabricated empty/zero data or a dry-run preview.
- Fresh desktop/tablet/mobile Chromium runs passed **12/12, 0 failed, 0 skipped, 0 flaky** per project; updated screenshots and reports are in `docs/automation/seller_runs/2026-10-19/ui-08-state-truthfulness/`.
- UI-08 remains **PARTIAL** because deterministic stubs do not prove persistence and the complete state matrix is not yet covered; the shared typed BFF/RFC7807 client contract is now verified separately under S-11.

### G6 PostgreSQL session-revocation integration — 2026-10-19

- Migrated a disposable PostgreSQL 16 database through `0064_seller_draft_autosaves` and ran the current session-revocation integration file against it. Logout-all and seller-suspension scenarios passed **2/2**; the suspension fixture now uses the current `SellerUser` plus `SellerMembership` auth model.
- Evidence: `docs/automation/seller_runs/2026-10-19/b2b-session-revocation/`. The temporary container was removed after the run; no production or shared data was accessed.

### G6 B2B PostgreSQL regression expansion — 2026-10-19

- Re-ran the selected live integration suites against a freshly migrated disposable PostgreSQL 16 database: autosave, session revocation, reservation invariants, export service, export scale and 100k inventory traversal.
- Result: **39 passed, 0 failed, 0 skipped** in 63.43 seconds; one existing Starlette/httpx deprecation warning. The temporary database container was removed after the run.
- Evidence: `docs/automation/seller_runs/2026-10-19/b2b-postgres-regression/`.

### G6 risk-register reconciliation — 2026-10-19

- Reconciled current implementation evidence with the Seller risk register: S-09 opaque sessions, S-11 typed Seller page/BFF client, S-12 correction resubmission and S-13 category/SKU wizard controls are now marked **RESOLVED** with current evidence links.
- Distributed request tracing through deployed workers and manual assistive-technology review remain separate follow-ups; they do not reopen the resolved page-client finding.

### G7 B2B request observability — 2026-10-19

- Added bounded JSON request records to the shared request-id middleware. Logs carry `request_id`, `trace_id`, service, deploy SHA, route template, status and duration; actor IDs are pseudonymized and concrete resource IDs/query data are excluded.
- Rebuilt the local B2B container and verified `GET /health` preserved a supplied correlation ID in both the response and the JSON log. Shared request-id tests passed 3/3 and B2B config/JWT tests passed 12/12.
- Evidence: `docs/automation/seller_runs/2026-10-19/observability-request-logs/`. Centralized shipping/OpenTelemetry and production deploy SHA injection remain deployment follow-ups.

- Full B2B regression after observability changes: `uv run --frozen pytest -q` passed **277**, skipped **38**, failed **0** in 6.59 seconds; two existing warnings remain. Evidence: `docs/automation/seller_runs/2026-10-19/b2b-full-regression/`.

### G7 S-18 media provenance and production CDN allowlist — 2026-10-19

- Centralized product/SKU image URL validation now requires HTTPS, rejects local/private/link-local hosts, and in production accepts only the configured `MEDIA_PUBLIC_BASE_URL` hostname. Missing production CDN configuration fails closed.
- Production and staging Compose now require `MEDIA_PUBLIC_BASE_URL` and `MEDIA_UPLOAD_SIGNING_SECRET` explicitly. The canonical Seller product flow remains based on seller-owned READY scanned media assets.
- Focused schema tests passed **10/10**; Ruff passed; all three Compose files parsed; full B2B regression passed **280**, skipped **38**, failed **0** with two existing warnings.
- S-18 is **RESOLVED** for URL provenance and current Seller media flow. Evidence: `docs/automation/seller_runs/2026-10-19/media-provenance/`.


### G6 S-19 moderation workflow reconciliation — 2026-10-19

- The Seller moderation screen already renders the server-backed decision timeline, reviewed revision, actor/ticket/reason metadata and field-level reports, with status filters and explicit read-only behavior.
- Existing UI-12 evidence passed desktop/tablet/mobile **1/1 each**, 27 backend tests, TypeScript and migration verification. S-19 is now **RESOLVED** in the authoritative risk register. Evidence: `docs/automation/seller_runs/2026-10-18/ui-12-moderation-timeline/`.


### G6 S-23 dashboard metric provenance reconciliation — 2026-10-19

- Dashboard KPI cards now decode the B2B dashboard metrics response and render the server-provided `as_of`; the inventory page uses the same owner-scoped summary endpoint. No Stitch demo KPI values are used in the live Seller view.
- Existing UI-02 browser evidence passed the live BFF/PostgreSQL parity checks on desktop/tablet/mobile and verified dashboard values against the summary API. S-23 is now **RESOLVED**. Evidence: `frontend/e2e/tests/userflows.spec.ts` and `docs/automation/evidence/seller-inventory-cursor-*.png`.


### G6 S-20 shared Seller shell — 2026-10-19

- Added `SellerSidebar` as the shared shell for all Seller route components. It owns the brand, responsive navigation, active route semantics, status badge and optional tenant/footer content; pages no longer carry private sidebar markup.
- The existing typed `sellerApiRequest` and `sellerErrorMessage` remain the common request/error semantics. Seller TypeScript passed, and the deterministic typed-client browser suite passed **24/24** across desktop, tablet and mobile.
- S-20 is **RESOLVED**. Evidence: `docs/automation/seller_runs/2026-10-19/s20-shared-shell/`.


### G7 S-14 upload abuse protection — 2026-10-19

- Seller media upload intents now use a seller-scoped Redis limiter: 30 requests per hour by default, HMAC-digested key, `429` with `Retry-After`, and fail-closed `503` when Redis protection is unavailable. The signed upload body remains limited to 10 MB and seller-bound.
- Focused limiter/media tests passed **11/11**; Ruff passed; the full B2B suite passed **283**, skipped **38**, failed **0**.
- S-14 remains **PARTIAL/OPEN** until MFA step-up and complete direct-backend/BFF IDOR probes are verified. Evidence: `docs/automation/seller_runs/2026-10-19/s14-upload-rate-limit/`.


### G8 SKU error-state recovery — 2026-10-19

- `frontend/apps/seller/src/SkusPage.tsx` now has a shared reload path, a visible `Повторить` action on request failure, and repaired Russian copy.
- TypeScript passed; the SKU request-failure browser scenario passed in desktop, tablet and mobile Chromium (3/3). Evidence: `docs/automation/seller_runs/2026-10-19/s21-sku-error-retry/`.
- UI-08 remains **PARTIAL** because the full Seller state matrix and backend persistence evidence are still incomplete.

### G9 responsive gate probe — 2026-10-19

- The current local responsive gate remains **BLOCKED** at Seller authentication: desktop, tablet and mobile all redirected to `/login?next=%2Fdashboard` after the login POST, so no authenticated viewport evidence was accepted.
- Evidence: `docs/automation/seller_runs/2026-10-19/s24-responsive-probe/`. The approved UI-04/UI-05 candidate baseline remains unchanged.

### G10 S-14 tenant isolation probes — 2026-10-19

- Updated the stale tenant-isolation fixture to create current `SellerUser` and `SellerMembership` records. In an isolated PostgreSQL 16 + temporary B2B runtime, foreign product read, SKU adjustment and seller order read each returned 404; owner-scoped product/inventory/order lists excluded foreign records, moderation and unknown import access returned 404, and the foreign SKU remained unchanged.
- The integration test passed **1/1**; temporary containers were removed and no production/shared data was used. Evidence: `docs/automation/seller_runs/2026-10-19/s14-tenant-isolation/`.
- S-14 remains **PARTIAL/OPEN** until MFA step-up and the complete endpoint matrix are verified.

### G11 S-14 BFF mutation guards — 2026-10-19

- Corrected the guard audit to accept equivalent conditional CSRF enforcement used by the draft-autosave proxy. The browser/source audit passed **3/3** Chromium projects; cross-site mutation returned 403 and no CORS origin was exposed.
- Evidence: `docs/automation/seller_runs/2026-10-19/s14-bff-guards/`. S-14 remains **PARTIAL/OPEN** pending MFA and full per-resource IDOR coverage.


### G12 Seller private route boundary ? 2026-10-19

- Expanded `frontend/apps/seller/middleware.ts` to protect imports, orders, team, finance, returns, settings, onboarding, analytics and support routes with bounded login redirects. The one-use `/team/accept-invite` onboarding surface remains explicitly public before a session exists.
- Anonymous boundary probes passed **10/10** protected routes plus **1/1** invite exception against a local Next server with `NEOMARKET_DEV_OPEN_ACCESS=false`; Seller TypeScript passed. Evidence: `docs/automation/seller_runs/2026-10-19/private-route-matcher/`.
- Commercial order/returns operations remain disabled pending the approved ADR decisions.


### G13 S-20 shared shell follow-up ? 2026-10-19

- Removed the remaining private sidebar markup from Team and Finance pages. Both now use `SellerSidebar`; Finance keeps explicit active state for overview versus payouts. A source audit found the sidebar markup owned only by `frontend/apps/seller/src/SellerSidebar.tsx`.
- Seller TypeScript passed. Evidence: `docs/automation/seller_runs/2026-10-19/s20-shared-shell-followup/`.


### G14 explicit blocked Seller route entrypoints ? 2026-10-19

- Added route entrypoints for `/onboarding`, `/analytics`, `/settings`, `/support` and `/returns`. They render the shared blocked state with the reason and never fabricate metrics or commercial outcomes; returns remains disabled until the approved ADR.
- Seller TypeScript passed for all five routes. Evidence: `docs/automation/seller_runs/2026-10-19/blocked-route-entrypoints/`.


### G15 authenticated responsive gate after migration alignment ? 2026-10-19

- The local B2B runtime was one migration behind the ORM (`0064` versus `0065_product_safety_holds`), causing a real Seller products 500. Applying the existing `0065` migration fixed the runtime defect without touching production data.
- Clean independent Playwright runs passed desktop, tablet and mobile Chromium **1/1 each**, covering all six required viewports and nine Seller screens (**162/162 observations**, zero overflow, broken images or unexpected browser errors). Finance remains an explicit `FEATURE_NOT_CONFIGURED` gate.
- Evidence: `docs/automation/seller_runs/2026-10-19/s24-responsive-authenticated/`.


### G16 local B2B migration startup guard ? 2026-10-19

- Added a one-shot `b2b-migrate` service to `docker-compose.yaml` and made `b2b` wait for `service_completed_successfully` before serving traffic. Compose config validation passed.
- Applied migration `0065_product_safety_holds` locally; the authenticated Seller products endpoint changed from the observed schema 500 to **200**. Evidence: `docs/automation/seller_runs/2026-10-19/b2b-migration-startup-guard/`.


### G17 current B2B regression after schema alignment ? 2026-10-19

- The complete B2B test suite passed **283**, skipped **38**, failed **0** after the `0065_product_safety_holds` migration and local Compose migration guard. Two existing dependency/security warnings remain documented. Evidence: `docs/automation/seller_runs/2026-10-19/b2b-full-regression-current/`.


### G18 keyboard focus current run ? 2026-10-19

- Clean Playwright keyboard/focus checks passed **9/9** across desktop, tablet and mobile Chromium; evidence was copied into the repository at `docs/automation/seller_runs/2026-10-19/ui-06-keyboard-focus-current/`. UI-06 remains PARTIAL because manual screen-reader and modal coverage is still required by the matrix.

### G19 product list contract and axe current run ? 2026-10-19

- Added `updated_at` to the verified B2B `ProductListItem` contract and seller projection, with a regression assertion in `services/b2b/tests/test_seller_product_list.py`. The focused B2B test file passed **7/7**.
- Clean axe-core WCAG 2.2 A/AA checks passed **3/3** projects, **17 screens per project / 51 scans**, with **0 violations**. UI-07 remains PARTIAL because automated axe coverage does not replace the required manual assistive-technology review. Evidence: `docs/automation/seller_runs/2026-10-19/ui-07-accessibility-current/`.


### G20 post-contract verification ? 2026-10-19

- Full B2B regression after the response-contract change passed **283**, skipped **38**, failed **0**; Seller TypeScript passed with `tsc --noEmit`. Evidence: `docs/automation/seller_runs/2026-10-19/b2b-full-regression-product-list-contract/`.

### G21 live Seller vertical smoke slice ? 2026-10-19

- The current Seller app and B2B services passed the selected live desktop vertical slice: **2/2 Playwright tests**, 0 failures. The product flow covered atomic 20-variant draft creation/replay, moderation transition, stock adjustment replay/conflict, inventory search, asynchronous CSV export and formula escaping; the dashboard flow covered live metrics/SKU rows and controls.
- The CSV assertion was aligned with the current asynchronous export contract: it waits for `Скачать CSV` after the job reaches `READY`, then verifies the downloaded file.
- This evidence does not close S-24: full Seller E2E, MFA/abuse scenarios, manual assistive-technology coverage, and commercial/returns flows remain open or disabled pending ADR. Evidence: `docs/automation/seller_runs/2026-10-19/s24-live-seller-vertical/`.

### G22 UI-08 current state matrix run — 2026-10-19

- Ran three independent clean Playwright projects against the current Seller app: desktop, tablet and mobile each passed **12/12**, for **36/36 total**, with no skips, flakes or failures.
- Coverage now includes loading/empty/error/pending/disabled behavior for products, orders, moderation, product detail, order detail, saved shipment, dashboard metrics, inventory, SKU detail, finance provider gate, team and inventory import.
- UI-08 remains PARTIAL because every Seller screen/state combination and backend persistence are not covered by deterministic browser route stubs. Evidence: `docs/automation/seller_runs/2026-10-19/ui-08-state-truthfulness-current/`.

### G23 blocked Seller entrypoints browser verification — 2026-10-19

- Added a browser test for `/onboarding`, `/analytics`, `/settings`, `/support` and `/returns`.
- Three independent Chromium project runs passed **3/3**, confirming each route renders an explicit `API CONTRACT PENDING` state, explains the missing contract, and does not render fabricated metric/table/card data. Returns remains disabled pending the commercial ADR.
- Evidence: `docs/automation/seller_runs/2026-10-19/blocked-route-entrypoints/`.

### G24 fail-closed Seller MFA contract — 2026-10-19

- Added authenticated B2B `/auth/mfa/challenge` and `/auth/mfa/verify` endpoints. Until the identity/MFA provider is approved, both return `501 FEATURE_NOT_CONFIGURED`; no fake challenge, token or bank-change approval is issued.
- Added Seller BFF routes with trusted-origin and CSRF enforcement before upstream forwarding.
- Backend regression passed **2/2** and Seller TypeScript passed. ID-16/FIN-11 remain PARTIAL/BLOCKED because the provider and bank-change policy are still not approved. Evidence: `docs/automation/seller_runs/2026-10-19/mfa-provider-gate/`.

### G25 full B2B regression after MFA contract — 2026-10-19

- Full `services/b2b` suite passed **285**, skipped **38**, failed **0** after adding the fail-closed MFA endpoints. Two non-failing dependency/security warnings remain documented.
- Evidence: `docs/automation/seller_runs/2026-10-19/b2b-full-regression-mfa-gate/`.

### G26 staging B2B runtime verification — 2026-10-20

- Fixed release `c073e7446d6d639f73644a1b68d2110ed234b325` is deployed on the staging host. Through the private gateway, B2B `/health` returned `{"status":"ok"}` and the live OpenAPI document exposed 97 paths.
- Anonymous and retired-route boundaries were checked against the real staging B2B service: wrong login `401`, seller metrics without a session `401`, retired legacy products `410`, private `/internal/*` route `404`, and unauthenticated MFA challenge `401`.
- The complete local B2B regression was rerun on the current checkout: **285 passed, 38 skipped, 0 failed**; Ruff, target OpenAPI route validation and Python compilation passed.
- Runtime evidence: `docs/automation/evidence/staging/b2b-runtime-smoke-20261020T120619Z.json` and `docs/automation/evidence/staging/b2b-local-regression-20261020.txt`.
- This verifies service startup, gateway boundaries and source regression only. Authenticated staging Seller flows, managed object storage, backup/restore, MFA provider step-up, and the ADR-disabled commercial/returns/finance requirements remain open or intentionally fail-closed.
