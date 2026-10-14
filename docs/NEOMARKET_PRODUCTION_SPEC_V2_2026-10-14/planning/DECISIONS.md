# Решения ADR и вопросы product owner

## Утверждённые **в рамках предлагаемой спеки** технические defaults (ADR must be signed before coding)

| ID | Decision | Reason | Alternative / trade-off |
|---|---|---|---|
| ADR-001 | Сохраняем FastAPI, SQLAlchemy async, Alembic, PostgreSQL, отдельные БД | уменьшает объём переписывания, изолирует ownership | полная миграция микросервисов даст дополнительные риски |
| ADR-002 | PostgreSQL transactional outbox/inbox + отдельные workers | атомарность с business rows без XA | Kafka/RabbitMQ optional later, сами по себе не решают transaction atomicity |
| ADR-003 | B2B persistent `order_id` lifecycle/tombstone | устраняет delayed reserve/cancel and TTL replay | краткий HTTP idem TTL не подходит |
| ADR-004 | Существующий physical `stock` становится `on_hand`, reserve отдельный | корректная семантика hold/release/fulfill | изменение физического stock при reserve ведёт к проблемам |
| ADR-005 | OIDC/SSO provider for Admin with MFA | нет доверия arbitrary headers | local auth only approved exception, сильные controls |
| ADR-006 | Internal mTLS + scoped service identity | zero-trust inside service network | временные shared keys не для full production |
| ADR-007 | API v1 from this repository contract package, not legacy NeoMarket canon | устаревшие требования отменены | принять новый versioned contract в repo |
| ADR-008 | explicit `202 PENDING` on durable unknown outcome | не заявляет ложное завершение | sync timeout/503 only if no intent exists |
| ADR-009 | fail-closed checkout/stock under uncertainty | предотвращение oversell и потерянных заказов | ниже availability, выше integrity |
| ADR-010 | immutable inventory ledger + order status history | reconciliation and forensic audit | more storage, documented retention |
| ADR-011 | no production online payments until PSP integrated and tested | enum PAID не равно денежный платёж | offline pilot only by explicit scope |
| ADR-012 | production HA across failure domains, offsite PITR | SLO/DR невозможно гарантировать на одном VPS | single-VPS staging/demo != full production |

## Открытые решения (все с безопасным default)

| ID | Вопрос | Default до утверждения | Владелец |
|---|---|---|---|
| O-01 | Юрисдикция данных, юридическое лицо, policy retention | avoid processing real PII; no public launch | product/legal |
| O-02 | Реальные способы оплаты, authorize/capture/refund | online pay disabled; no arbitrary PAID | product/finance |
| O-03 | Курьеры, доказательство доставки, частичные отгрузки | manual authenticated full-order delivery only; no partial | operations/product |
| O-04 | Возвраты после fulfill и delivery | unsupported in v1, no ad-hoc stock restore | product/finance |
| O-05 | Поддержка валют, налогов, минимальные цены | RUB only, price minor integer >=0; tax must be specified to sell | finance |
| O-06 | Peak RPS, daily orders, SKU count, concurrency | must be measured and agreed before performance gate | product/SRE |
| O-07 | Infra budget, RPO/RTO and multi-region | target 99.9%, RPO5m/RTO60m; no claim till drills | SRE/business |
| O-08 | Merchant settlements, commissions, payouts | no payouts without approved ledger | finance |
| O-09 | Who may mark delivered/override cancelled | trusted audited operator, restricted roles | operations/security |
| O-10 | User authentication provider, password/local migration | OIDC (admin mandatory MFA) | security |
| O-11 | Data existing and needed migration downtime | expand/backfill/contract; explicit freeze window | database team |
| O-12 | Delete/retention for terminal lifecycle | retain until order legal lifetime; compact tombstone if needed | product/legal |

**Process:** every ADR has decision owner, date, rationale, measured costs, migration/rollback plan. Unresolved O-01/O-02/O-03/O-06/O-07/O-08 where applicable block claim of *full* marketplace production; safe defaults can allow clearly labeled narrower launch **only after** security/data integrity DR gates.
