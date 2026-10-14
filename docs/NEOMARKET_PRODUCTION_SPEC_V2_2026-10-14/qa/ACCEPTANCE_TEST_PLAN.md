# QA — Стратегия верификации, матрица тестов и выпускные доказательства

## QA-001. Уровни и среда испытаний

1. Unit: pure state machines, Pydantic models, numerical limits, all error branches. Property based for states/fingerprints.
2. Integration: **реальный PostgreSQL** (3 независимые БД), asyncpg, Alembic, Redis если реально нужен. Нет подмены критичного SQL fake repository. Transaction rollback and multiple DB sessions under load.
3. Contract: automatically generated live `/openapi.json` vs `contracts/http-*.openapi.yaml`, JSON Schemas as validation, consumer uses producer serialized payload; negative/extra fields and version mismatch.
4. E2E: public B2C, seller B2B, private Admin over HTTPS gateway + identities; committed flows and asynchronous outcomes with 2+ worker processes.
5. Fault injection: deliberate network drop, DB restart, lock delay, process SIGKILL, lost ACK, out-of-order event, DLQ/poison, interrupted migrations and PITR.
6. Security: OWASP ASVS 5.0.0-based test plan; network scan, SAST, DAST, dependency, authentication/authorization, SSRF/resource consumption and manual pentest.
7. Performance: >=2x documented expected peak RPS, >=3x expected catalog/orders, weighted traffic mix, 24h soak, DB load/locks/IOPS, worker backlog, P50/P95/P99 and memory peaks.
8. DR: offsite restore with chosen PITR, simulated loss primary, cross-service reconciliation, RPO/RTO measured. No destructive fault tests on production database.

**Command policy:** use repo's pinned Python 3.12 + uv lock; `uv sync --frozen --all-packages --dev`, pytest of all three `services/*/tests`, not selective smoke; tests requiring infrastructure run against isolated ephemeral DB. Original snapshot had pytest import error `asyncpg` in audit environment; don't represent as passed. Build jobs may include `ruff check .`, `mypy`, secret/SBOM/SAST; adapt exact syntax once tool versions pinned.

## QA-002. Перечень обязательных тестов

| ID | Class | Test / proof | Pass condition |
|---|---|---|---|
| SEC-T01 | Auth | Missing/forged/expired JWT, wrong issuer/audience/alg | all protected mutations rejected, 0 state changes |
| SEC-T02 | Auth | Header spoof `X-Moderator-Id` | no role gained; 401/403 |
| SEC-T03 | Authz | Seller/user queries other owners' IDs | 0 disclosure/mutations |
| SEC-T04 | Service auth | Wrong/missing scope, wrong service identity | denied and logged |
| SEC-T05 | Sessions | Refresh token reuse/revocation/JWKS rotation | replay detected, old tokens invalid per policy |
| SEC-T06 | Abuse | Login 100 wrong attempts, body size/depth stress | bounded resources, 429/413/422, no 500 OOM |
| SEC-T07 | Network | External host scan DB/Redis/Admin/internal | inaccessible externally |
| SEC-T08 | Secrets | Release without secrets/dev secrets | startup fail fast |
| SEC-T09 | Security | Pen test incl OWASP API1/2/3/4/5/7 | no unwaived Critical/High |
| INV-T01 | Concurrent | 100 simultaneous reserves 1 SKU | not oversold; SUM active=reserved |
| INV-T02 | Concurrency | reserve vs seller lowers on_hand | no stock below reserved |
| INV-T03 | Race | unreserve commits before in-flight reserve | terminal tombstone, no active reserve |
| INV-T04 | Replay | reserve retry after 1h/24h/30d | no double reserve |
| INV-T05 | Idempotence | same idem key, altered qty/items | 409, 0 extra mutations |
| INV-T06 | Lifecycle | parallel cancel vs fulfill | exactly one terminal outcome, 0 double stock effects |
| INV-T07 | Deadlock | two orders reversed item ordering | no permanent lock, sorted lock handling |
| INV-T08 | Failure | kill process at each reserve/unreserve/fulfill checkpoint | atomic invariants hold |
| INV-T09 | DB | negative price/stock, `reserved > on_hand` direct SQL | DB CHECK rejects |
| INV-T10 | Ledger | 1k randomized state sequences with fixed seeds | ledger totals match SKU state |
| INV-T11 | Policy | blocked/deleted/inactive SKU reserved | 409 no reserve |
| INV-T12 | Reconcile | inject orphan/mismatch in isolated DB | detector alerts, no silent correction |
| ORD-T01 | Checkout | B2B reserve commit, HTTP response lost | B2C recovers via same ID |
| ORD-T02 | Checkout | B2B reserve commit, B2C dies before commit | commit or durable compensating state |
| ORD-T03 | Checkout | duplicate idem request from 20 clients | one Order, one lifecycle |
| ORD-T04 | Checkout | idem key reused with different address/items | 409 no duplicate |
| ORD-T05 | Checkout | timeout after durable intent | 202 operation persisted and pollable |
| ORD-T06 | Cancel | B2B unreserve unavailable then recovers | pending -> cancelled, no orphan |
| ORD-T07 | Cancel | concurrent cancellation and delivery | no CANCELLED+DELIVERED same order |
| ORD-T08 | Fulfill | delivery ack lost and worker retry | 1 stock decrement |
| ORD-T09 | Fulfill | worker disabled and restarted | backlog drains, alert triggered |
| ORD-T10 | Price | source price modified during checkout | repricing/reject safely, no trusting cart price |
| ORD-T11 | History | seller edits product after order | immutable order items/prices |
| ORD-T12 | PII | buyer attempts GET and cancel other order | 403/404 no leakage |
| ORD-T13 | Payment | browser claims PAID without provider proof | rejected/no state change |
| ORD-T14 | Load | checkout under overload/downstream unavailable | bounded pending 202 or 503, no fake 201 |
| EVT-T01 | Event | actual B2B product.created bytes sent Admin | ticket persisted, no KeyError |
| EVT-T02 | Event | real Admin decision -> B2B | correct revision applied; outbox durable |
| EVT-T03 | At least once | 3 workers, ACK lost post-consumer commit | one effect, original event ACKed later |
| EVT-T04 | Atomicity | producer local rollback after creating outbox | no remote mutation; one commit boundary |
| EVT-T05 | Integrity | same event_id, different payload | 409 conflict, alert |
| EVT-T06 | Ordering | arrival versions 1,3,2 | final revision 3, no rollback |
| EVT-T07 | Delete | product.delete revision then old edit arrives | product stays deleted/unavailable |
| EVT-T08 | Claim | stale moderator lease submits approve | 409, 0 new applied decisions |
| EVT-T09 | Queue | create/claim/release/expire/decision | valid transitions and RBAC |
| EVT-T10 | Poison | invalid schema and DLQ/replay | no infinite tight loop; alerts |
| EVT-T11 | E2E | seller product -> approved -> B2C visible | visible only after correct approval |
| EVT-T12 | E2E | block product with existing orders | not newly sellable; existing orders handled policy |
| API-T01 | Contract | method/path/schema/auth/status diff for all enabled APIs | zero drift; CI blocked on diff |
| API-T02 | Error | validation, JSON parse, auth and DB outages | error.code/request_id stable, no secrets |
| API-T03 | Pagination | million SKU list w/ indexed filter/cursor | bounded memory, stable pages |
| API-T04 | Limits | image URL/mime/json over limits | safe rejection, no SSRF/private host fetch |
| MIG-T01 | Migration | upgrade fresh+realistic anonymized DB | all migrations succeed without data loss |
| MIG-T02 | Migration | repeat/restart batch backfill | safe idempotent completion |
| MIG-T03 | Migration | old/new app during expand | no incompatible field errors |
| MIG-T04 | Migration | incorrect existing stocks/duplicates | preflight stops and reports |
| MIG-T05 | Migration | lock and query plan budgets | meets approved maintenance window |
| OPS-T01 | Runtime | external port scan, restart API/workers | no exposed DB/admin, graceful restart |
| OPS-T02 | Worker | crash/leasing 3 workers | no duplicate effect, backlog drains |
| OPS-T03 | Metrics | dead worker, P0 stock mismatch, WAL lag | page within threshold |
| OPS-T04 | Rollout | canary elevated 5xx/latency | abort and code rollback; DB compatible |
| PERF-T01 | Load | catalog high-cardinality filters @2x forecast | p95/p99 SLO, no OOM |
| PERF-T02 | Soak | 24h representative workload | no memory leak, no rising queues/stuck jobs |
| DR-T01 | Restore | restore offsite copy to clean isolated host | all databases start and pass invariants |
| DR-T02 | PITR | restore known point in time | achieved measured RPO <= target |
| DR-T03 | Multi-DB | one DB ahead/behind other two | reconciliation finds discrepancy and safe fixes |
| DR-T04 | Disaster | primary loss and controlled failover | RTO measured <= target, no fake success |
| DR-T05 | Security | compromise backup access/revoke | backup remains recoverable and isolated |
| BUS-T01 | Scope | if no PSP, payments API/PAID transitions unavailable | no misleading paid state |
| BUS-T02 | PSP | if PSP enabled: duplicate signed webhook, failed capture, refund, fraud | no extra charges/refunds, provider reconciliation |
| BUS-T03 | Logistics | carrier duplicate delivery/returns | 1 delivery event and 1 fulfill effect |

## QA-002B. Дополнительные обязательные тесты до покрытия полного перечня требований

| ID | Scenario | Pass condition |
|---|---|---|
| ORD-T15 | 202 checkout operation checked after service restart | operation id and state not lost |
| ORD-T16 | Quote/price changed after buyer confirms cart | 202 while compensation pending, then 409; zero orphan reservations |
| ORD-T17 | Stale worker fencing token after lease takeover | stale worker cannot commit/compensate newer state |
| ORD-T18 | Delivered after cancel request and vice versa, randomized | exactly one legal outcome and accurate history |
| API-T05 | Pending checkout polling | stable operation ID, Location, no false committed 201 |
| API-T06 | Idem 200 + conflicting 409 | no extra side effect |
| API-T07 | Object-level authorization for each route | no cross-owner leak |
| API-T08 | Schema equality of serialized responses | all required fields present and typed |
| API-T09 | API version compatibility test | v1 behavior unchanged during v2 transition |
| API-T10 | Internal route public exposure test | external access fails even with guessed URI |
| API-T11 | Forbidden order/moderation state transitions | 409 without commit |
| API-T12 | Timeouts from HTTPX/DB mapped to safe response | 202 only if durable, otherwise 503 |
| MIG-T06 | Binary rollback while expanded schema remains | no incompatibility |
| MIG-T07 | Interrupt and restart backfill midway | exact same final values |
| MIG-T08 | Deadlocks/restarts on DB session | bounded retry + atomicity |
| MIG-T09 | FK/UNIQUE/CHECK DB negative cases | DB rejects malformed inserts |
| MIG-T10 | Restored DB migrations and DB role permissions | correct revision, least privilege |
| OBS-T01 | `/ready` while DB unavailable | 503 and correct non-secret diagnostic |
| OBS-T02 | Worker kill, API healthy | alert triggered; backlog tracked |
| OBS-T03 | Poison outbox | DLQ alert, unrelated messages progress |
| OBS-T04 | Two workers claim same event concurrently | exactly one active lease, one effect |
| OBS-T05 | P0 alert delivery to primary/secondary | ack/escalate within approved window |
| OBS-T06 | Log scraping and audit redaction | zero secrets, passwords, raw PII in log output |
| OBS-T07 | Trace checkout/reserve and cancel compensation | shared correlation id + linked spans |
| OBS-T08 | Inject stock and moderation mismatch into staging | detector identifies precise pair and incident |
| DR-T06 | Rotate/revoke compromised backup credential | restored from independent safe copy |
| DR-T07 | Backup bucket immutability / encryption audit | cannot delete within retention with runtime user |
| DR-T08 | Quarterly full failover drill | actual measured RPO/RTO within target |

## QA-003. Severity blocking

- **Critical**: auth bypass, public DB, secrets exposed, integrity invariant broken, inconsistent final order, restore failure — **NO-GO**.
- **High**: outbox stuck with no alert/retry, lost moderation event, wrong tenant data, unreliable migrations, unattained agreed RPO/RTO — **NO-GO**.
- **Medium**: no unaccepted P2 for full production. Allowed exceptions only in genuinely non-security optional features under time-bounded signed waiver.
- Zero data loss claims require proof for **a specified failure domain** and designed topology. No invented probability percentages.

## QA-004. Test reports/evidence

CI must save test manifest + commit SHA, environment versions, database image digest/migration revision, exact command and exit code, passed/failed/skipped, load scenario config, fault seeds, sanitized logs/traces, sample contract request/response, restore timestamps/actual RPO/RTO, sign-off. Every skipped Critical test = NO-GO. Own risk -> trace table `planning/RISK_TRACEABILITY.csv`.
