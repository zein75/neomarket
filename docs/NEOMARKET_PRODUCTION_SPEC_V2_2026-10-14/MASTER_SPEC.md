# NeoMarket — Master Production Specification v2.0

**Новая независимая production-спецификация (14.10.2026).** Нет зависимости от устаревших канонов и OpenAPI. **Не является доказательством реализации.** Для машинных контрактов, схем, SQL blueprint и реестра рисков используйте полный архив.


---

<!-- Source: README.md -->

# NeoMarket — новая спецификация полного production release

**Версия:** 2.0 (проект целевого состояния). **Дата:** 2026-10-14. **Решение по исходному состоянию:** NO-GO. **Статус реализации требований:** NOT IMPLEMENTED / NOT VERIFIED, до предоставления CI и эксплуатационных доказательств.

## Авторитетность и область применения

Этот комплект намеренно **не опирается на старые NeoMarket canon, старые протоколы и прежние OpenAPI**. Они объявлены устаревшими и не используются ни как требования, ни как проверка соответствия. Источник фактов о текущей реализации — `neomarket-audit.zip` от 14.10.2026 и исходный статический аудит `evidence/BASELINE_AUDIT.md`. **С данного релиза нормативными** становятся тексты `spec/*`, машинные контракты `contracts/*`, утверждённые ADR, миграции и проверяемые acceptance criteria. Исходный код сам по себе не подменяет спецификацию. Если настоящее ТЗ вступает в противоречие с существующей реализацией, реализацию меняют с миграциями и документируемой совместимостью.

**Цель:** безопасный и восстанавливаемый production B2B+B2C+Admin для каталога, продавцов, модерации, корзин, заказов, управления SKU, резервов, исполнения заказов и их отмены. Реальные онлайн-платежи, выплаты продавцам, фискализация, налоговый учёт и интеграция перевозчиков **не подтверждены исходниками** и потому вынесены в самостоятельный обязательный scope-gate: если бизнес требует их на запуске, они не могут быть объявлены готовыми или имитироваться статусом `PAID`; нужны отдельные интеграции, контракты, комплаенс и тесты (см. `spec/11_PAYMENTS_DELIVERY_AND_BUSINESS.md`). До решения продуктового владельца режим запуска — **без онлайн-эквайринга и без обещания автоматизированной доставки**. Не объявлять «полный marketplace production» при отсутствии фактически требуемых платежей, возвратов, логистики.

## Правила нормативности

- `MUST`/«ОБЯЗАТЕЛЬНО» — блокирует публичный релиз; `SHOULD` — допускает только письменное принятие риска с владельцем/датой; `MAY` — опционально.
- **P0/P1/P2 из аудита должны быть исправлены и подтверждены испытаниями** для заявленной полной готовности. Сокрытие endpoint, зелёный статический анализ или fake-unit-test не считаются исправлением.
- **Сначала безопасность/backup, затем миграции и целостность, затем запуск.** На production никогда не выполнять необратимые миграции без восстановимого backup и плана остановки.
- Новые OpenAPI и JSON Schema в `contracts/` — **целевые эталонные контракты**, а не описание текущих маршрутов. Для production должны быть дополнены всеми публично включёнными операциями, приняты владельцем продукта, и проверяться против реально сгенерированных `/openapi.json`.
- Если сервис/продукт не поддерживает требование, это фиксируется как невыполненный критерий, а не «готово по умолчанию».
- Гарантии сети: **at-least-once delivery; effectively-once business effects** при идемпотентных транзакциях; exactly-once delivery через HTTP не обещается.

## Структура

| Документ | Назначение |
|---|---|
| `spec/01_ARCHITECTURE_NFR.md` | границы, компоненты, ownership, инварианты, SLO и деградации |
| `spec/02_SECURITY_IDENTITY.md` | модель угроз, RBAC, JWT/OIDC, сервисная авторизация, защита API |
| `spec/03_INVENTORY_DATA_MODEL.md` | остатки, блокировки, ledger, lifecycle резерва и антигоночные гарантии |
| `spec/04_ORDERS_CHECKOUT_SAGAS.md` | статусные модели, checkout, cancellation, delivery/fulfillment, восстановление |
| `spec/05_EVENTS_MODERATION.md` | transactional outbox/inbox, event versioning, очередь модерации |
| `spec/06_API_AND_ERROR_CONTRACTS.md` | новый API, ошибки, идемпотентность, пагинация, совместимость |
| `spec/07_DATABASE_MIGRATIONS.md` | схемы БД, миграции без потери данных, целостность, retention |
| `spec/08_INFRA_DEPLOY_CICD.md` | сеть, TLS, контейнеры, rollout, CI/CD, supply chain |
| `spec/09_BACKUP_DR.md` | backups, PITR, DR, невозможные гарантии, restore test |
| `spec/10_OBSERVABILITY_RUNBOOKS.md` | метрики, алерты, мониторинг, инциденты, эксплуатация |
| `spec/11_PAYMENTS_DELIVERY_AND_BUSINESS.md` | отсутствующие бизнес-процессы, платежи/возвраты/доставка/PII |
| `qa/ACCEPTANCE_TEST_PLAN.md` | детерминированные и аварийные тесты с идентификаторами |
| `planning/IMPLEMENTATION_PLAN.md` | этапы, затрагиваемые файлы, зависимости и доказательства |
| `planning/RISK_TRACEABILITY.csv` | сквозная трассировка 26 рисков -> требования -> тесты -> этапы |
| `planning/DECISIONS.md` | закрытые ADR и открытые бизнес-вопросы (с безопасным default) |
| `contracts/*.yaml` и `contracts/*.json` | новые проверяемые целевые контракты (HTTP/event) |
| `db/SCHEMA_BLUEPRINT.sql` | референс DDL **для проектирования**, НЕ исполнение на существующей БД |
| `operations/GO_LIVE.md`, `INCIDENTS.md`, `BACKUP_RESTORE.md` | эксплуатационные процедуры |
| `evidence/BASELINE_*` | результаты предыдущего аудита, только для контекста |

## Обязательные вехи

**Gate 0: Fence** — запрет небезопасной публикации, отключение legacy inventory, безопасные ключи. **Gate 1: Data safety** — tested backup+restore, план миграций и доработка DB constraints. **Gate 2: Correctness** — запас/резерв/отмена/fulfill и модерация выдержали реальные конкурентные fault tests. **Gate 3: Operability** — отдельные worker, метрики, alerts, масштабирование, hardened deploy. **Gate 4: Release** — полное прохождение матрицы, DAST, нагрузка/soak, DR drill, sign-off бизнес-владельца и SRE/security; включение трафика по canary. Чеклист в `operations/GO_LIVE.md`.

## Предпочитаемый стек

Не переписывать ради переписывания: Python 3.12, FastAPI, SQLAlchemy asyncio, Pydantic v2, PostgreSQL (поддерживаемая и закреплённая версия), Alembic, HTTPX с таймаутами, отдельные workers на PostgreSQL outbox. Redis необязателен, не source of truth. API gateway с HTTPS и OIDC/OAuth 2.0 provider; OpenTelemetry/Prometheus-совместимые метрики. Staging имеет те же конфигурационные механизмы, но полностью отдельные учётки, ключи и данные.

## Что доказано и что нет

Аудит 14.10.2026: обнаружены **6 P0, 13 P1, 7 P2**. Проверка обнаружила 281 тестовую функцию, но полноценный pytest не завершился из-за отсутствия `asyncpg`; БД/кластер/восстановление/нагрузка не запускались. Этот документ **не утверждает**, что исправления применены, миграции безопасны или значения SLO достигнуты. План внедрения сопровождается обязательными артефактами, которые позже позволят законно изменить статус NO-GO на GO.

## Информационные стандарты (не заменяют тесты)

OWASP ASVS 5.0.0; OWASP API Security Top 10 (2023); действующая документация PostgreSQL PITR. Эти внешние инженерные стандарты допустимы, в отличие от устаревших документов NeoMarket. Юридические требования определяются выбранной юрисдикцией и консультацией профильного специалиста.


---

<!-- Source: spec/01_ARCHITECTURE_NFR.md -->

# 01 — Целевая архитектура, не-функциональные требования, границы

## ARCH-001. Система и ownership

```text
Internet Web/Mobile ------HTTPS------> Edge/WAF/Rate limiter/Request-ID
Seller portal -------------HTTPS------> Gateway [public B2C + seller B2B]
Operator portal -----VPN/SSO+MFA-----> Gateway [private Admin only]
                                              |
                                +-------------+-------------+
                                |             |             |
                          B2C API/worker  B2B API/worker  Admin API/worker
                                |             |             |
                            B2C PG         B2B PG        Admin PG
                                +---- trusted services ----+
                                durable outbox/inbox + auth
                                         |
                            metrics, structured logs, traces
                                         |
                     PITR encrypted offsite backup + restore evidence
```

- **B2B** — единственный владелец продавца, товаров/SKU, цены в каталоге, физического доступного остатка, резервов, списаний и статуса публикации.
- **B2C** — единственный владелец покупателей, адресов, корзин, заказов, статусов checkout/cancel/fulfill и immutable снимков позиций, цены и условий на момент заказа.
- **Admin** — единственный владелец ролей модераторов, очереди задач, claims/leases, решений, причин блокировки, защищённого журнала. Admin **не** пишет в БД B2B.
- Отдельная БД/схема/роль с least-privilege и миграции на сервис. Никаких прямых SQL join между сервисами в online-пути.
- HTTP ingress для внутренних `/internal/v1/*` — только service mesh/приватная сеть, с отдельной сервисной аутентификацией и авторизацией. Trust boundary проверяется даже в приватной сети.
- Worker deploy = отдельный процесс/реплики от ASGI API, с durable очередью на PostgreSQL. Redis разрешён только как удаляемый cache/ratelimit store и не является ledger/источником состояния заказов.

## ARCH-002. Ключевые продуктовые цепочки

1. Продавец создаёт draft продукта и SKU -> запись + outbox в одной транзакции -> Admin получает версионированный snapshot -> создаёт задачу -> модератор claim+decision -> outbox Admin -> B2B применяет decision только к правильной revision -> outbox B2B -> B2C меняет read model видимости.
2. Покупатель добавляет товар -> checkout создаёт durable intent -> B2B резервирует SKU с per-order terminal marker -> B2C фиксирует заказ -> запрос показывает только подтверждённый результат или `PENDING` -> delivery/fulfill с exactly-once business effect.
3. Отмена -> в БД B2C фиксируется `CANCEL_PENDING` и durable команда -> B2B отменяет резерв или возвращает terminal outcome -> B2C фиксирует `CANCELLED`. При timeout допускается `CANCEL_PENDING`, **не** `CANCELLED`.
4. Падение любого узла -> API отвечает корректным pending/503 и worker продолжает обработку. Неизвестный результат вызова не означает неуспешный вызов.

## ARCH-003. Сквозные бизнес-инварианты

| ID | Требование (обязательно) |
|---|---|
| INV-01 | `on_hand >= 0`, `reserved >= 0`, `reserved <= on_hand`, `available=on_hand-reserved >= 0`, `price_minor>=0`, валюта допустима; цены и суммы в целых минорных единицах, все вычисления без float. |
| INV-02 | `reserved` равен сумме ACTIVE reserve lines SKU при одном устойчивом snapshot/транзакции; все изменения защищены блокировкой и/или DB CAS. |
| INV-03 | Каждый `order_id` имеет максимум один lifecycle в B2B; нельзя открыть reserve после `CANCELLED`/`FULFILLED`, даже если TTL idem HTTP истёк. |
| INV-04 | Повтор той же операции с тем же fingerprint возвращает сохранённый результат; другой fingerprint с тем же `order_id`/идемпотентным ключом -> 409, без эффекта. |
| INV-05 | Успешный fulfillment ровно один раз уменьшает on_hand на quantity и releases reserved; запрещён `max(...,0)` как маскировка ошибки. |
| INV-06 | Переход B2C в `CANCELLED` возможен только после достоверного terminal результата B2B; в `DELIVERED` — только после зафиксированного fulfill либо промежуточного `DELIVERY_FINALIZING`. |
| INV-07 | Неавторизованный/неодобренный товар не продаётся; резерв всегда повторно проверяет soft-delete, активность, модерацию, price policy и доступность SKU. |
| INV-08 | Данные и outbox event записываются одним DB commit; потребитель сохраняет dedup и бизнес-эффект одним commit. |
| INV-09 | Producer versions на aggregate монотонно растут; старый snapshot не может восстановить ранее заблокированный или удалённый товар. |
| INV-10 | Неизвестный/отсутствующий downstream-ack никогда не отражается как финальный business success. |
| INV-11 | Финансовые статусы, если включены, основаны на проверенных платежных событиях/аккаунтинге, а не пользовательских полях. |
| INV-12 | Восстановление баз на разные точки времени требует cross-service reconcile и управляемого устранения несоответствий **до** возобновления записи. |
| INV-13 | Исторические данные заказов (название, цена, налог, адрес доставки) остаются снимками, изменение текущего каталога их не переписывает. |
| INV-14 | Клиент имеет доступ только к своим объектам; продавец только к своим товарам; модератор только к дозволенным действиям. |

## ARCH-004. Нефункциональные цели (targets, ещё не измеренные)

| SLI | Release target | Подтверждение |
|---|---|---|
| Доступность внешнего read/write API | 99.9% в календарный месяц, error budget=43.2 мин в 30-дневном месяце | synthetic probes снаружи + server availability |
| 5xx на штатном профиле | <=0.5% за 30 дней | gateway metrics; аварийные периоды учитываются отдельно |
| p95 `GET /catalog` | <=500 ms, p99 <=1200 ms | нагрузка, заранее утверждённый объём данных |
| p95 checkout sync request | <=2 s на нормальном пути; более длительная межсервисная сага -> `202 PENDING` | benchmark + pending polling |
| p95 moderator decision submit | <=600 ms локальный durable commit (без ожидания remote) | staging load |
| Outbox publish lag p95 | <=30 s, p99 <=120 s | created_at -> ack_at |
| Critical alert delivery | <=2 мин от начала устойчивого нарушения | тест alert routing |
| Необъяснённые расхождения reserve/stock | 0 | каждые 5 мин reconciliation; инцидент на любое отклонение |
| Recovery DB tier: RPO/RTO | предложено <=5 мин / <=60 мин при отказе узла/сайта в рамках выбранной топологии | DR drill с измерением; разные failure classes |
| Recovery на уровне отдельного API процесса | RTO <=5 мин | kill+restart drill |
| Backups | daily base + непрерывный WAL, защищённые off-site копии, месячные restore drills | backup+WAL lag alarms |
| Пиковая нагрузка | >=2x прогнозируемого peak RPS и >=3x начального каталога в staging | согласованный профиль, soak >=24ч |

Числа — минимальные критерии приемки для предлагаемого начального релиза, не утверждения о достижении. Для SLO 99.9% нужна инфраструктура без явных single points of failure: одноразовый VPS не удовлетворяет полноценной модели отказоустойчивости.

## ARCH-005. Graceful degradation и backpressure

- Потеря Admin: B2B принимает черновики локально, ставит в outbox, но не публикует их; пользователю виден `PENDING_MODERATION`.
- Потеря B2B: просмотр кэшированных B2C товаров может работать с явной свежестью; checkout fail-closed с `202 PENDING` только при уже сохранённом intent, либо `503` до создания intent. Никаких «заказ оформлен» до commit и подтверждённого reserve.
- Потеря B2C: B2B может продолжать управление продавцами; операторы видят backlog, никаких прямых резервов из B2B UI.
- Потеря Redis: не теряются заказы/резервы, rate-limit gateway выбирает консервативную политику, возможна ограниченная деградация.
- DB/Pool exhaustion: readiness 503, bounded wait, timeout, idempotent retry клиента, backpressure; не бесконтрольный рост task memory.
- Каждый asynchronous job имеет owner, next_retry_at, attempt count, DLQ, replay и alert. Запрещены бесконечные silent loops и `except: pass`.

## ARCH-006. Версионирование/изменения

- Внешний HTTPS API `/api/v1`, внутренний `/internal/v1`, event envelope `schema_version=1`. Несовместимые изменения -> v2 с period of dual support и sunset date.
- Новые контракты определяет **этот** пакет и исходная спецификация в репозитории на дату релиза; старые canon/protocols не используются для acceptance.
- Релизные артефакты содержат tag/commit SHA, image digests, DB migration heads и contract hash.


---

<!-- Source: spec/02_SECURITY_IDENTITY.md -->

# 02 — Безопасность, идентификация, авторизация, privacy

## SEC-001. Threat model и границы доверия

Объекты: credentials, JWT/refresh tokens, seller/buyer/moderator identities, PII (телефоны, адреса), активы продавца (SKU, цены, статус), заказ/резерв, аудит модерации, DB backups, service secrets. Противники: анонимный интернет-клиент, зарегистрированный покупатель, продавец с чужими ID, скомпрометированный сервисный ключ, злонамеренный сотрудник, атакующий цепочку поставки и аварийный оператор. STRIDE: spoofing через `X-Moderator-Id`, tampering через legacy reservations/Stock update, repudiation без audit, info disclosure via open DB/error responses, denial of service через каталог/bcrypt, elevation of privilege via shared tokens.

## SEC-002. Человеческая идентификация

- Для покупателей/продавцов **MUST** проверять JWT `iss`, `aud`, `exp`, `nbf`, `iat`, `sub`, approved `alg`, `kid`, подпись JWKS; запрещены `alg=none`, fallback на известный local secret и использование неподтверждённых claims.
- Рекомендуемый путь: один OIDC провайдер (authorization code+PKCE для browser/mobile), `aud` раздельный для API, роли/тенант принадлежность проверяются на сервере. Если сохраняется локальная auth — отдельный approved ADR, независимое хранение password hash, сессии/refresh rotation, защита reset; вне `DEBUG` запуск при слабой конфигурации запрещён.
- Для администраторов обязательно SSO/OIDC с MFA (предпочтительно phishing-resistant), подтверждённая активная запись оператора в Admin DB и role-scope; `X-Moderator-Id` **не** удостоверяет identity. `actor_id` извлекается исключительно из проверенного principal.
- JWT TTL: access 10–15 мин (проектный default 15); refresh до 30 дней с rotation, хеш в БД, семейство токенов и reuse detection; logout/revoke-all и блокировка пользователя отзывают refresh, а критические операции учитывают active/revoked account по DB/инвалидируемому кэшу.
- Пароль при локальной auth: Argon2id либо сопоставимый актуальный алгоритм, параметр измеряется под нагрузкой; пароль не логировать и не хранить в plaintext; reset одноразовый, TTL <=15 мин, без account enumeration.
- Owner check на **каждый** `order_id`, `cart_id`, `address_id`, `product_id`, `sku_id`, `ticket_id`; row-scoped query или explicit 403/404 without data leakage. Разрешённые поля update перечислять явно (запрет mass assignment).

## SEC-003. Матрица RBAC/ABAC

| Операция | Guest | Buyer (owner) | Seller (owner) | Moderator | Admin/SRE svc |
|---|---|---|---|---|---|
| Public catalog | read | read | read | read | scoped read |
| Cart own | scoped ephemeral | CRUD own | no | no | support audited |
| Checkout/cancel order | no | own | no | no | operator only with separate scope + reason |
| Product/SKU edit | no | no | own | no | break-glass audited |
| Moderation claim/decision | no | no | no | assigned ticket + permission | admin role / controlled workflow |
| Moderator role management | no | no | no | no | security admin w/ MFA + dual approval |
| Internal reserve/unreserve/fulfill | no | no | no | no | only service principal `b2c-order` with granular scopes |
| Read/download backup | no | no | no | no | isolated backup operator identity |

Продавец не может изменять reserved_quantity напрямую и уменьшать on_hand ниже резерва. Модератор не может назначить себе глобальную роль или принять решение по чужому claim без explicit privileged override с аудитом.

## SEC-004. Межсервисная идентификация

- Internal requests require **mTLS + short-lived service token** with mutually verified identity (либо равносильное подтверждённое gateway/workload identity решение), `aud` specific receiver, fine-grained scopes `inventory.reserve|unreserve|fulfill`, `moderation.events.write`, `moderation.decisions.write`, `catalog.events.write`.
- Нельзя передавать один общий `X-Service-Key` всем сервисам; при миграции временно разрешить dual credentials только по IP/service identity и измеряемый sunset, после выключить.
- Validate caller, token issuer/audience/scope, replay semantics and request body; service token не переносить из фронтенда. TLS verify `true`; no `verify=False`.
- Сервисный endpoint никогда не доступен через внешний gateway; firewall/ingress default-deny, no public ports 5432/6379/8003/internal.
- Секреты в secret manager/host vault с безопасной выдачей, rotation, access auditing и kill switch. Fail-fast для пустого, известного dev/default секрета.

## SEC-005. Защита HTTP/web

- TLS 1.2+ (предпочтительно 1.3), HSTS после проверки домена, secure/same-site/httponly cookie для browser auth, CSRF при cookie-based mutations, narrowly scoped CORS allowlist, CSP и output escaping в UI.
- Per-IP/per-identity/per-scope adaptive rate limits, отдельно login/reset/registration/checkout/expensive catalog, concurrency caps, body <=256 KiB JSON (кроме upload), query cardinality limit; 429 + Retry-After.
- Request `Content-Type`, JSON nesting/depth/length, UUID, integers and images validation; лишние поля для write схем отклоняются `extra=forbid`; максимум 100 items/order (релизный default, уточнить бизнесу), max 100 qty/line с общей бизнес-границей.
- API errors: fixed safe codes, request_id, никаких stacktrace/sql/internal hostnames/JWT/reused client secrets. Логи маскируют PII, access credentials, payloads внутренних событий с PII.
- Image: только безопасные `https` CDN URLs из allowlist либо media IDs; если upload используется — max size, content sniffing, scan, isolation, transform, presigned URL TTL, запрет SVG inline и SSRF/private-IP redirects. Сервер не загружает arbitrary user URL.
- SAST/DAST, dependency/SBOM scan, CVE severity gate, секреты/PII in logs scan, external pentest до публичного запуска и после важных auth/payment changes.

## SEC-006. Хранение и право доступа к данным

- DB отдельные роли `*_runtime` (DML в своей БД), `*_migrator` (DDL controlled job), `*_readonly` для observability/backup. Никакой root/superuser из приложения; сеть БД только от своего runtime/backup.
- At-rest encrypted disks and backups, encrypted transport, secret keys separate from backup; лог доступа к backup.
- Retention by purpose: session/refresh до истечения+security retention, guest carts default 30 дней, доставленные необязательные outbox events 30 дней после подтверждения и audit, moderator decision/audit и order financial history по утверждённой правовой политике. **Не удалять terminal reservation lifecycle, пока ссылки/регуляторные требования требуют защиты от replay;** допускается compacted immutable tombstone.
- Export/deletion requests, unlink/anonymize PII without destroying order consistency; процесс доступа сотрудников и incident notification определяется юрисдикцией. Локация хранения/юридическое основание должны быть письменно определены до старта.

## SEC-007. Приёмка

SEC-T01: 100% protected endpoint negative test без credentials/с forged JWT; SEC-T02: `X-Moderator-Id` без bearer токена -> 401; SEC-T03: другой seller/user -> 403/404, 0 mutations; SEC-T04: service token wrong aud/scope -> 403; SEC-T05: JWKS rotation, token expiry/revocation; SEC-T06: brute force threshold/429; SEC-T07: нет публичного DB/admin/internal, сетевой smoke-test из внешней сети; SEC-T08: backup access isolation; SEC-T09: dynamic pentest без критических/высоких незакрытых findings. Проверяемый артефакт — CI reports + network scan + security sign-off.


---

<!-- Source: spec/03_INVENTORY_DATA_MODEL.md -->

# 03 — Строгая спецификация склада и резервов

## INV-DM-001. Термины и источник истины

В B2B хранить `skus.on_hand` (текущее фактическое количество, бывшее `stock`), `skus.reserved_quantity` (активные брони), `available=on_hand-reserved_quantity` (вычисляемое значение), `skus.price_minor`, `currency`. **Не** менять `on_hand` при `reserve`; при `unreserve` уменьшается только `reserved_quantity`; при `fulfill` уменьшаются оба `on_hand` и `reserved_quantity`. `stock` -> `on_hand` мигрировать expand/backfill/contract, не rename в один шаг при работающих клиентах. Если бизнес допускает отрицательные остатки/backorder — отдельная сущность и ADR, текущий релиз запрещает.

## INV-DM-002. Транзакционные таблицы

- `inventory_order_lifecycle`: `order_id UUID PK`, `fingerprint char(64)`, `state ENUM(NEW, RESERVED, CANCELLED, FULFILLED)`, `version BIGINT`, `reserved_at`, `terminal_at`, `source`, `created_at/updated_at`, `result JSONB`; терминальные записи не исчезают по short TTL.
- `reservation_lines`: `order_id`, `sku_id`, `quantity>0`, `state ACTIVE|RELEASED|FULFILLED`, unique `(order_id,sku_id)`; FK order_lifecycle, FK sku, timestamps. Исторические строки остаются для reconciliation.
- `inventory_ledger`: append-only `entry_id`, `event_id UNIQUE`, `order_id nullable`, `sku_id`, `delta_on_hand`, `delta_reserved`, `reason`, `actor_type/id`, `occurred_at`, `correlation_id`; изменения ledger и skus обязаны совершаться в одном commit.
- `inventory_request_keys`: `(caller,idem_key)` PK, `order_id`, `fingerprint`, `response/status`, TTL только для кэша HTTP ответа, никогда не для контроля order terminal lifecycle.
- `stock_adjustments`: adjustment_id, sku_id, delta, reason, seller_id, idempotency key; видимые продавцу изменения только через этот audit-able workflow.

## INV-DM-003. DB constraints и обновления

```
CHECK on_hand >= 0
CHECK reserved_quantity >= 0
CHECK reserved_quantity <= on_hand
CHECK price_minor >= 0
CHECK reservation_lines.quantity > 0
UNIQUE (order_id, sku_id) on reservation_lines
UNIQUE (sku_id, event_id) or UNIQUE(event_id) inventory_ledger
```

- Плюс `NOT NULL`, FK, допустимые статусы, объём/длина строк, индекс `(state, next_retry_at)` у jobs. Потребуются migration preflight и устранение существующих нарушений; constraint лучше добавить `NOT VALID` / `VALIDATE CONSTRAINT` по поддерживаемой схеме.
- Всегда блокировать `inventory_order_lifecycle` по `order_id`, затем `skus` **в отсортированном UUID порядке**, затем `reservation_lines`; глобальный lock order одинаков для reserve/cancel/fulfill/update, чтобы избежать deadlock. Для отсутствующей lifecycle записи сначала `INSERT .. ON CONFLICT DO NOTHING`, затем `SELECT .. FOR UPDATE`; конкурентные reserve и unreserve сериализуются на одном ключе, даже до появления строк reserve.
- SKU update должен блокировать строки SKU, проверять `new_on_hand >= reserved_quantity` и не менять reserved; если нет запаса -> `409 STOCK_BELOW_RESERVED` со safe details.
- `READ COMMITTED` + explicit row locks достаточен при доказанной сериализации на order id и sorted SKUs. При SQLSTATE 40001/40P01 bounded retry всей транзакции с jitter; не повторять произвольный side effect вне DB transaction.
- Любая ловимая аномалия -> rollback, error event, alert, без использования `max(quantity,0)` в качестве «исправления».

## INV-DM-004. Reserve: строгий алгоритм

1. Проверить service identity/scope, JSON Schema, тот же normalized fingerprint: отсортированные `sku_id`, без дублей/нулевых/отрицательных qty, количество товаров в пределах limits.
2. BEGIN; создать lifecycle row `order_id` при отсутствии, `FOR UPDATE`; если `CANCELLED/FULFILLED` -> 409 `ORDER_TERMINAL`, **никаких резервов**, если `RESERVED` и fingerprint равен -> ответ из сохранённого state, иначе 409 `IDEMPOTENCY_CONFLICT`.
3. `SELECT skus WHERE id IN ... ORDER BY id FOR UPDATE`; все SKU существуют/active/sellable/approved и имеют `available >= requested qty`. Price snapshot/B2C quote policy проверяется в документе order saga.
4. Atomic update `reserved+=qty`, вставить lines, ledger с `delta_reserved=+qty`, lifecycle state `RESERVED`, outbox события для B2C при необходимости; COMMIT.
5. Ответ `201` (новый), `200` (идемпотентный повтор); timeout after commit не означает отсутствие reserve.
6. При недостатке доступности **ни один SKU не резервируется**; rollback всей операции, 409 `INSUFFICIENT_STOCK` с sku_id and available (если разрешено скрывать внешним клиентам, B2C переводит в понятную ошибку).

## INV-DM-005. Unreserve: tombstone раньше/после reserve

1. BEGIN; создать lifecycle row для `order_id` при отсутствии (state `NEW`); заблокировать `FOR UPDATE`.
2. `NEW` -> записать **terminal** `CANCELLED` (tombstone), `delta=0`, COMMIT `200 CANCELLED`. Это навсегда предотвращает «опоздавший reserve».
3. `RESERVED` -> lock SKU sorted, verify line quantities, уменьшить reserved exactly, перевести lines `RELEASED`, lifecycle `CANCELLED`, append ledger, COMMIT. Повтор -> прежний результат.
4. `CANCELLED` -> `200` с сохранённым outcome (при совпадающем semantic scope); `FULFILLED` -> `409 ALREADY_FULFILLED` (отмена после отправки/доставки ведёт в отдельный returns workflow, не увеличивать склад произвольно).
5. Неправильные списки items из external request не влияют на lines: источник истины — B2B линии по order_id. При любом несовпадении fingerprint — `409 IDEMPOTENCY_CONFLICT`.

## INV-DM-006. Fulfill

`NEW` -> 409 `NOT_RESERVED`; `CANCELLED` -> 409; `FULFILLED` -> прежний `200`. Для `RESERVED`: order row lock, sorted SKU locks; проверка всех lines/stock; `on_hand-=qty`, `reserved-=qty`, lines `FULFILLED`, lifecycle `FULFILLED`, ledger per SKU, outbox ack, COMMIT; любое нарушение abort transaction и critical alert. Не допускать partial fulfill для v1; если понадобится частичная поставка, вводить `shipment_id` и отдельный ledger/idempotency contract.

## INV-DM-007. Reconciliation и очистка

- Каждые 5 мин B2B SQL-проверка `reserved_quantity` vs sum of ACTIVE lines, nonnegative/check constraints, orphan lifecycle/reservation/ledger; любые отличия -> P0 incident + stop writes affected SKU, безопасная повторная проверка, ручной approved repair via ledger.
- Каждые 5 мин cross-service reconcile: B2C orders statuses vs B2B lifecycle (через signed paginated admin endpoint/инкрементальные агрегаты). `CREATED/RESERVED`, `CANCEL_PENDING/CANCELLED`, `DELIVERY_FINALIZING/FULFILLED` разбирать по матрице, непонятные состояния -> queue, не silent auto-delete.
- Garbage collection только после запрета replay через retained lifecycle tombstone (business retention >= life of order/retention policy). Нельзя удалять идемпотентность бизнес-транзакций из-за часового TTL.

## INV-DM-008. Обязательные конкурентные тесты

100 параллельных reserve одной SKU; reserve vs stock decrease; reserve slow vs unreserve first; retry after 1/24/720 часов; concurrent fulfill+unreserve; 3 SKU с разным порядком в запросах; deadlock injected; kill after each BEGIN/lock/ledger/commit/response; crash worker and retry; 1k random sequences (property-based state machine). Для каждого: сумма активных линий=reserved, никогда минус, terminal lifecycle не воскресает, exactly one fulfillment effect. См. `qa/ACCEPTANCE_TEST_PLAN.md`.


---

<!-- Source: spec/04_ORDERS_CHECKOUT_SAGAS.md -->

# 04 — Заказы, checkout, отмена, доставка, платежные статусы

## ORD-001. Ownership и статусы

B2C — единственный источник истины для покупателей, заказов и истории; B2B — для броней, физического остатка и fulfillment. В `orders` сохранить immutable snapshots SKU, названия, quantity, `unit_price_minor`, currency, address, delivery method, tax/shipping (когда применимо), total and created_at; изменения товара не переписывают историю заказа. `orders.version` для CAS optimistic concurrency. Платёжный статус не смешивается со статусом логистики.

**Состояние checkout_intent:** `NEW → RESERVING → RESERVED → COMMITTED` либо `RESERVING/RESERVED → COMPENSATING → COMPENSATED`; неопределённые результаты — `RECONCILE_REQUIRED`, окончательный отказ `FAILED_FINAL` после проверки отсутствия активной брони. Intent содержит `order_id`, `(buyer_id,idempotency_key) UNIQUE`, normalized fingerprint, immutable items, `lease_owner`, `lease_until`, monotonically increasing fencing_token, retry_count, next_retry_at, status. Один B2C owner на intent.

**Заказ:** `CREATED → CONFIRMED → ASSEMBLING → DELIVERING → DELIVERY_FINALIZING → DELIVERED` или (если отмена допустима до delivery) `CREATED|CONFIRMED|ASSEMBLING → CANCEL_PENDING → CANCELLED`. `DELIVERING` отменяется только по утверждённым правилам возвратов; нельзя молча снимать бронь после физической передачи. `CANCELLED` и `DELIVERED` терминальны; post-delivery return — отдельный workflow.

**Оплата:** отдельно `NOT_REQUIRED | PENDING | AUTHORIZED | CAPTURED | FAILED | REFUND_PENDING | REFUNDED`. Из frontend нельзя напрямую выставить CAPTURED/PAID; online PSP обязателен, если заявлены платежи.

## ORD-002. Checkout: идемпотентный commit and unknown outcomes

1. Подтвердить JWT, owner корзины/адреса, все quantities>0, ограничения суммы/списка SKU, seller and publication. **Не доверять** переданной клиентом цене: snapshot корзины строится сервером и подтверждается покупателем.
2. Client `POST /api/v1/orders`, `Idempotency-Key` UUID. Canonical hash B2C из user_id, нормализованных items, address version, delivery method, currency. Unique per-user request key. Тот же key+hash возвращает прежний result, тот же key+другой hash -> 409.
3. BEFORE downstream HTTP: `BEGIN` B2C, записать durable checkout_intent with immutable proposed order_id, `COMMIT`. Если создание intent не удалось, никаких резервов. Worker or request leases intent with SELECT FOR UPDATE SKIP LOCKED+fencing.
4. B2B `reserve(order_id,items,request_fingerprint)` is protected, terminal-marker aware and idempotent. Семантический B2B fingerprint отдельный: canonical hash только `order_id + normalized sku_id/qty`, B2B **пересчитывает его**, не доверяет произвольной строке из HTTP. B2C request fingerprint/quote включает более широкие client fields.
5. B2B returns durable `RESERVED` plus authoritative price snapshot in `items[]`: sku_id,product_id, quantity,unit_price_minor,currency,product_revision. B2C сравнивает с **последней серверной ценой показанной покупателю**; при изменении вызывает durable `COMPENSATING -> unreserve` того же order_id. До terminal ack -> 202 PENDING; после terminal ack клиент получает `409 PRICE_CHANGED` с приглашением подтвердить новую цену.
6. При совпадении prices и valid lease/fencing B2C в одной транзакции INSERT order/items/history, intent `COMMITTED`, outbox notifications, commit. Только после durable commit возвращать 201. Idem replay returns 200.
7. B2B reserve response timeout/connection reset => **UNKNOWN**, не трактовать как неуспех. Повтор с тем же order_id и semantic hash; если операция уже идёт, возвращать `202 PENDING` только при committed intent и stable operation poll URL, не создавать второй заказ.
8. Если процесс умер after B2B commit, before B2C commit, worker выясняет через exact order_id и либо безопасно завершает order, либо сперва фиксирует `COMPENSATING` затем вызывает B2B `unreserve`/terminal tombstone. После перехода в COMPENSATING поздний worker/HTTP request **не может** создать Order.

**Инвариант:** для каждой успешной 201/200 операции есть единственный B2C order и один B2B RESERVED lifecycle с идентичным SKU snapshot; если не удалось, возможен только честный pending или terminal compensated. Ни orphan reserves, ни утверждений success при неизвестном outcome.

## ORD-003. Cancellation

- Buyer (owner) or audited operator: `POST /orders/{id}/cancel`; compare-and-set status -> `CANCEL_PENDING`, persist `cancel_job`/outbox and history **в одной B2C транзакции**, return 202 if pending.
- Worker with durable lease calls protected B2B `unreserve(order_id)`. B2B `CANCELLED` -> B2C final `CANCELLED`, `FULFILLED` -> 409 and supervised returns/dispute, unknown -> retry same ID+backoff, no premature CANCELLED.
- Concurrent cancel and fulfill serializable per order (B2C version and B2B lifecycle row lock); stale command safe and idempotent. Optional requested reason bounded and sanitized.
- Failure before/after B2B unreserve commit or client response reconstructed by replay. No direct DELETE reservation endpoint.

## ORD-004. Delivery and fulfillment

- Only authenticated and audited fulfillment operator/carrier principal can confirm delivery; proof/correlation/timestamp, scope `delivery.confirm`. Browser user cannot set DELIVERED. Confirm changes B2C `DELIVERING→DELIVERY_FINALIZING`, adds durable pending fulfillment with retry state.
- Dedicated fulfillment worker calls B2B `fulfill` exactly one business effect. B2B state `FULFILLED` -> B2C `DELIVERED`, save history/ack. On outage order remains `DELIVERY_FINALIZING`, with backlog alert; never claim DELIVERED on unacknowledged external change.
- Retry/delayed response and duplicate delivery webhook cannot decrement `on_hand` twice. Unsupported partial fulfill forbidden until shipment_id/item-level ledger and separate ADR are built. Delivered returns are an independent compensated flow, not unreserve.

## ORD-005. Error contract & state graph acceptance

| Failure point | Recovery invariant |
|---|---|
| Before checkout intent commit | no B2B reserve and no order |
| After intent commit, before reserve | worker resumes same order_id |
| After reserve commit, response lost | B2B idem replay, no extra hold |
| After reserve, before order commit | intent worker either completes or cancels, never both |
| Unreserve wins before old reserve | B2B tombstone prevents late reserve |
| Cancel after fulfill | explicit conflict/returns case, no stock resurrection |
| Fulfill completed, HTTP ACK lost | repeat -> same result, order eventually DELIVERED |
| 2+ B2C workers | lease/fencing prevents concurrent decisions, repeats remain safe |
| DB restored at different times | freeze unsafe writes, reconcile, replay same IDs |

409: wrong state/price changed/insufficient stock/semantic conflict; 503: unavailable before any durable operation; 202: operation saved and pollable, not completed. Error payload `error.code/message/details/retryable`, request_id. Status histories append-only, API only returns order owner data.

## ORD-006. Testing

ORD-T01..T18, INV-T03..T08, DR-T03 and SEC-T03 tests from `qa/ACCEPTANCE_TEST_PLAN.md`: parallel checkout, lost reply, crash around every commit, cancel vs delivery, duplicate webhook, price change, timeout, 202 polling, same and altered idempotency keys, client owner/access checks. Real PostgreSQL/2+ workers, randomized seeds, no fake repository as exclusive evidence.


---

<!-- Source: spec/05_EVENTS_MODERATION.md -->

# 05 — Transactional outbox/inbox, упорядочивание и модерация

## EVT-001. Единый контракт

Machine-readable `contracts/event-envelope-v1.schema.json`: `schema_version=1`, `event_id` UUID stable across retries, `event_type`, `producer`, `aggregate_type`, `aggregate_id`, `aggregate_version>=1`, `occurred_at` RFC3339 UTC, `correlation_id`, nullable `causation_id`, typed `payload`. Event id and customer idempotency key are distinct. `contracts/product-event-v1.schema.json` and `contracts/moderation-event-v1.schema.json` define exact producer/consumer payload.

- B2B -> Admin: `product.created | product.updated | product.deleted`, `payload.product_id`, `seller_id`, `revision`, `deleted`, product+SKU snapshot. Admin cannot look for `event['product_id']` at top level. On created event, it **must** create a moderation ticket; silently IGNORED is a defect.
- Admin -> B2B: `moderation.approved | moderation.blocked | moderation.hard_blocked`, ticket/decision_id, `reviewed_revision`, verified `actor_id`, reason.
- B2B -> B2C: `catalog.visibility_changed | catalog.sku_changed` with aggregate version; B2B source of truth for published status. Internal inventory events for reconciliation; B2C order status events optional for read models.

## EVT-002. Producer outbox

**One local DB transaction** commits business rows + outbox event, never an HTTP call before local commit. Outbox: event_id PK, event_type, destination, payload, sha256, aggregate/version, status PENDING|LEASED|RETRY|SENT|DEAD, attempts, `next_retry_at`, lease_owner/until/token, error code and times.

Dedicated worker(s) `SELECT ... FOR UPDATE SKIP LOCKED` claim batch and persist lease. Sends scoped mTLS+bearer request. 2xx durable receipt -> SENT; timeout/5xx unknown -> RETRY same event_id; 429 Retry-After; 401/403 -> config/security incident; invalid permanent schema -> DEAD with alert, no silent discard. Backoff capped (initial e.g. 2^n sec, max 15 min ±jitter); dead-letter after e.g. 12 attempts with manual replay privileges. 2+ workers safe. On lost acknowledgment, consumer might have succeeded — publisher must retry **unchanged** event ID/payload.

## EVT-003. Consumer inbox & ordering

Consumer first validates service principal, event JSON schema and version; single `BEGIN` inserts unique `(producer,event_id)` with SHA-256. Same ID+hash -> prior 200 and no mutation; same ID+changed payload -> 409 `EVENT_ID_CONFLICT` and security log. Consumer domain mutation, inbox receipt, and any response outbox are committed atomically. 2xx only AFTER DB commit. Network at-least-once, domain effects effectively once.

B2B product revisions monotonically grow on all publish-relevant edits; Admin stores `last_source_revision`. `aggregate_version<=current` -> stale safe ack (must not revert state), `==current+1` -> apply, `>current+1` -> parked `WAITING_GAP`, request authoritative versioned snapshot; delete tombstone stops resurrection. Admin decision scoped to `reviewed_revision`: B2B rejects stale moderation decision without making product sellable and creates new review task. B2C projection version check same rules.

## MOD-001. Queue and decisions

On first valid `product.created` (real B2B serialized payload), Admin stores immutable product/SKU snapshot and ticket `PENDING` keyed by `(product_id,revision,kind)`. On edit: previous undecided revision becomes SUPERSEDED, new ticket PENDING. On deleted: close tasks, block visibility of product. Ticket state: `PENDING→IN_REVIEW→APPROVED/BLOCKED/HARD_BLOCKED`; `IN_REVIEW→PENDING` on release/expired lease; either -> SUPERSEDED by new revision. Hard block terminal pending privileged appeal workflow.

Claim `SELECT FOR UPDATE SKIP LOCKED`, set moderator verified user + lease expiry + fencing_token, unique active claim. Decision requires active owner+unexpired lease+current version, privilege by role, audit reason, full snapshot; stale token -> 409. Decision commit includes ticket status, immutable decision/audit row, outbound event in same transaction. Because B2B apply is asynchronous, response 202 `DECISION_PENDING_APPLY`; UI displays applied_at and any conflict/lag. Approve must **not** publish SKU before B2B revision-matched apply. Blocked/deleted immediately fail B2B inventory reserve sellability check even if B2C projection lags (B2B final truth).

## MOD-002. Security and audit

Admin SSO/OIDC MFA, real active moderator DB identity, role/scope and object-level checks. Header `X-Moderator-Id` never authenticates. Admin action append-only log of actor, scope, target, before/after digests, reason, correlation_id, timestamp. Runtime DB role cannot UPDATE/DELETE historical audit; export/retention protected; break-glass privilege audited separately.

## EVT-004. Reconciliation & monitoring

- Worker metrics: oldest pending event age, backlog count, attempts/DEAD, throughput, lease expired, 401/403, aggregate gaps; poison messages never starve healthy aggregates.
- Every 5min compare Admin last_source_revision and B2B latest revision, B2B publish state vs B2C projection, pending decisions and inbox receipts. Manual replay uses same event_id only after root cause approval, with audit.
- Outbox/inbox retention cannot be shorter than replay horizon or aggregate version/tombstone memory. Never clean old processed_event and allow duplicate business side effect.

## EVT-005. Required tests

EVT-T01 real B2B producer bytes -> persisted Admin ticket (fix KeyError); EVT-T02 Admin decision -> B2B revision gated; EVT-T03 duplicate after lost ack; EVT-T04 remote side effect never if local rollback; EVT-T05 event ID collision; EVT-T06 out-of-order 1,3,2; EVT-T07 delete then stale edit; EVT-T08 stolen/stale moderator claim; EVT-T09 claim/queue/release; EVT-T10 poison DLQ; EVT-T11 seller→approved→B2C E2E; EVT-T12 block product and test new reserve rejected.


---

<!-- Source: spec/06_API_AND_ERROR_CONTRACTS.md -->

# 06 — New canonical HTTP API & stable error semantics

## API-001. Authoritative contract

Old NeoMarket canon, old protocols and previous OpenAPI are **obsolete**, never authoritative. The normative planned API is `contracts/http-b2c.openapi.yaml`, `contracts/http-b2b.openapi.yaml`, `contracts/http-admin.openapi.yaml` and events JSON schemas, plus this specification and approved ADRs. CI compares generated live OpenAPI method/path/auth/request/response/status/errors against these new files; no undocumented route enabled in production. Relative JSON Schema refs inside OpenAPI point to files in same `contracts/` directory. Production domain values `example.invalid` MUST be replaced in deployment OpenAPI server configurations; no real endpoint at these placeholder hosts.

## API-002. Boundaries / services

- **Public B2C** `/api/v1/catalog`, `/api/v1/catalog/{product_id}`; buyer auth/session provider; cart items & buyer addresses (only own), `POST /api/v1/orders` with `Idempotency-Key`, `GET /api/v1/checkout-operations/{operation_id}`, `GET /api/v1/orders[/{id}]`, `POST /api/v1/orders/{id}/cancel`. Responses include 200 idem replay, 201 committed new order, 202 persisted pending operation. See schemas for accepted fields and status types.
- **Seller B2B** `/api/v1/seller/products`, `/api/v1/seller/products/{id}`, `/skus/{id}`, `/stock-adjustments` by authorized owner; new products queued for moderation, all edits versioned; cannot set reserved_quantity or moderation state through public body; stock adjustment always ledger/audit.
- **Private Admin** `/admin/v1/moderation/tickets[/{id}]`, claim, heartbeat, release, decisions and audit; OIDC+MFA, active moderator account, claim lease/fencing. Do not expose Admin routes to public internet; never trust X-Moderator-Id.
- **Internal** `/internal/v1/inventory/reserve|unreserve|fulfill|orders/{order_id}` B2C service only; `/internal/v1/events/products`, `/events/moderation`, `/events/catalog` service-to-service with mTLS and scoped service token. No anonymous legacy `/reservations` write routes. Private route omitted from public gateway deployment.
- Public UI features outside v1 declared scope (payment methods, returns, seller settlement, invoices etc.) MUST have separate, reviewed new API schemas and gate before any UI integration. All enabled routes, including preexisting routes not in these OAS files, must be either intentionally retired or added to the new contract; no silent accidental exposures.

## API-003. Unified HTTP error contract

```json
{
  "error": {
    "code": "STOCK_BELOW_RESERVED",
    "message": "Requested stock adjustment is not available",
    "details": {"sku_id": "c2b30000-0000-4000-8000-000000000001"},
    "retryable": false
  },
  "request_id": "c2b30000-0000-4000-8000-000000000099"
}
```

Use stable codes: MALFORMED_JSON=400, AUTHENTICATION_REQUIRED=401, FORBIDDEN=403, NOT_FOUND=404, VALIDATION_ERROR=422, IDEMPOTENCY_CONFLICT / PRICE_CHANGED / INSUFFICIENT_STOCK / STOCK_BELOW_RESERVED / INVALID_STATE / ORDER_TERMINAL=409, RATE_LIMITED=429 (+Retry-After), UPSTREAM_UNAVAILABLE/DEPENDENCY_UNAVAILABLE=503, INTERNAL_ERROR=500. HTTP 401 supplies WWW-Authenticate. No SQL tracebacks, internal address, raw downstream exception, secrets or PII in response. Each response includes request_id/traceparent headers. Unknown HTTP POST result only 202 with persisted operation and Location polling, else 503 if nothing durable.

## API-004. Body/schemas/consistency

- Write Pydantic v2 extra='forbid' on unsafe operations, UUID format, bounded arrays and strings, `quantity>=1`, max 100 lines and 100 qty/line default, integer minor currency, RFC3339 UTC; maximum body 256KiB for JSON via gateway, larger uploads separate safe service.
- `reserve` canonical semantic hash derived by B2B from `(order_id,sorted sku_id quantities)`, B2C never changes order_id on retries. B2B response must include immutable authoritative unit price+currency+revision snapshot per line. B2C compares with shown/accepted cart price and initiates cancellation on mismatch.
- Stable cursor pagination, max limit 100, allowed indexes/sorts. No unbounded Python filtering of whole catalogs.
- Seller/product/buyer ownership checked per object at DB query boundary, admin routes only active principals, internal endpoints scoped per destination+operation.
- Public `Idempotency-Key` per buyer/operation. Same key+same hash -> same outcome. Same key+different hash -> 409. Race handling/retention defined in spec/03 and spec/04.

## API-005. Schema change policy

Incompatible changes -> `/api/v2` or `schema_version=2` with dual consumers, deprecation schedule and tested migration. Preprod compares all live `/openapi.json` to the target YAML; additions also require approved contract PR and regression tests. No consulting obsolete canons to infer expected endpoint behavior.

## API-006. Acceptance

API-T01 full route/security/schema diff 0 for **every** enabled handler; API-T02 standardized errors; API-T03 paginated large catalog under load; API-T04 image/protocol/JSON malformed rejection; API-T05 202 persisted checkout/poll, API-T06 200 idem replay/409 conflict; API-T07 auth ownership; API-T08 response/schema serialization; API-T09 version bump safe; API-T10 internal unexposed; API-T11 status transition policy; API-T12 controller/cloud-client timeout mapping.


---

<!-- Source: spec/07_DATABASE_MIGRATIONS.md -->

# 07 — PostgreSQL, миграции без потери данных и обслуживание

## DB-001. База данных — граница атомарности

Все доменные операции и соответствующие записи `outbox_events`, `inbox_events`, `audit` либо `inventory_ledger` в пределах **одного** owning DB commit. Изоляция READ COMMITTED с documented row locks; no implicit auto commit в nested repositories, единый transaction boundary в service layer, HTTP remote calls outside transactions. Транзакция должна быть короткой (не ждать сеть/платежи).

- PostgreSQL выделенная поддерживаемая версия, у каждого сервиса отдельные DB+runtime/migrator/readonly учетные роли, TLS, pool budget. Названия всех миграций/версий сохраняются в release manifest.
- По БД: `statement_timeout` default 10s для request traffic (исключения явно заданы), `lock_timeout` default 2s, `idle_in_transaction_session_timeout` default 15s, `pool_pre_ping`, `max_overflow`, `pool_timeout`; реальные значения после нагрузочных измерений. Job transaction может иметь отдельный timeout.
- Все таблицы с timestamp UTC, server_default NOW() с tz-aware, immutable IDs UUID, целые суммы `BIGINT`/`NUMERIC(20,0)`. Никаких `float` для денег, миграционные преобразования из `Integer` с проверкой диапазона.

## DB-002. Обязательные изменения

**B2B:** SKU `price_minor`, `on_hand`, `reserved`, CHECK nonneg+reserved<=on_hand; `inventory_order_lifecycle` с PK order_id и terminal flags; `reservation_lines` with unique order+sku+state; `inventory_ledger` append only; `stock_adjustments`; product revision; unified outbox with lock metadata; normalized inbox+dedup. Доработать индексы `(status,next_retry_at,lease_until)`, `(sku_id,state)`, `(product_id,revision)`.

**B2C:** checkout_intents c durable lease/fencing, request hash, unique `(buyer_id,idempotency_key)`; orders with version and stable amount fields; cancel_jobs and fulfillment_jobs with retry metadata; processed events with content hash; status_history immutable; cart qty CHECK > 0; quote snapshot; account sessions/revocations; audit of sensitive operator actions.

**Admin:** moderation_tickets keyed `(product_id,revision,kind)`, SKU snapshots/version, claim lease/fencing, decision history, outbox/inbox, audit_events append only, moderator accounts bound to SSO subject. Unique active claim semantics and active ticket constraint (use conditional partial index if possible), index queue priority/created_at.

**Cross-cutting:** DB indexes supporting request patterns and workers, retention job table, schema migration history, keys for event ledger, no app writes as DB superuser.

## DB-003. Expand/migrate/contract без блокировки

1. **Inventory existing data preflight**: before any DDL, run SELECT-only checks for negative stock/price, reserved > stock, duplicate `(order_id,sku_id)`, active reservation quantity mismatch, orphan `order_id`, malformed UUID/key/JSON events, orders with cancel_pending > threshold, terminal orders still reserving, invalid moderators. Save signed reports.
2. **Safety**: freeze risky legacy endpoints, verify tested PITR and encrypted offsite backup, dedicated rollback snapshot, approve maintenance and communication; take metrics baseline.
3. **Expand**: add nullable/parallel new columns/tables/indexes `CONCURRENTLY` where supported (outside transaction as required), triggers only if independently justified and reviewed; do not drop existing columns.
4. **Backfill**: batches of e.g. 1000 rows (configurable), keyset paging with checkpoints, updates with idempotent run IDs, bounded lock time, monitor WAL/bloat/replica lag. Never backfill live reserved state from unreliable duplicated operations without business reconciliation.
5. **Dual-compatible deployment**: new code reads old/new or dual-writes where necessary; dual-write done in a single transaction, read compare logs; outbox producer changes behind versioned flags.
6. **Validate**: `CHECK NOT VALID` then `VALIDATE CONSTRAINT`, FK migration verify, new unique indexes and query plans; run concurrent E2E, staged original dataset anonymized copy.
7. **Switch**: enable new endpoints/worker gradually, compare invariants, ensure monitoring; turn off legacy endpoints and serializers; verify canary.
8. **Contract**: after documented compatibility window and rollback window, remove old columns/routes in separate migration. No `DROP` with active consumers.

**Важно:** `db/SCHEMA_BLUEPRINT.sql` — schema proposal, его нельзя исполнять на существующей БД напрямую. Каждое изменение создаётся отдельной Alembic revision с specific preflight, forward and app-level rollback notes, migration owner and migration SQL reviewed.

## DB-004. Rollback и несовместимость

- Code rollback возможно только если schema still backwards-compatible; миграции forward-only by default for data-migration steps. Если rollback requires destructive reversion, **не** делать destructive downgrade; fail closed, restore from PITR to staging/recover via documented repair job and incident approval.
- One-shot migration job with exclusive deploy coordination; **никаких Alembic upgrade в CMD каждой API реплики**. Before migrate verify DB endpoint/environment, backup restorable, available disk>=estimated WAL/data, user approval. Validate `alembic current` and post smoke.
- Zero-downtime применим только для изменений со строгим expand/contract. Нельзя обещать безостановочность для специфичных DDL без тестов live-equivalent DB.

## DB-005. Health / retention / backup

- Monitoring: connection saturation, max locks, deadlocks, long txns, replication lag, WAL archiving, disk, slow queries, bloat/vacuum, index scan pattern. Pool sizes across replicas must fit Postgres `max_connections` with headroom for backup/admin.
- Daily job retention: guest sessions/cart cleanup with safe null user, delivered outbox data archiving after retention and compacted tombstones; processed event retention cannot be shorter than retry/replay horizon or aggregate version protection. Never bulk delete active holds/jobs.
- Dedicated index/partition strategy for outbox, logs and order history only after measured growth; large user deletion follows anonymization policy.

## DB-006. Required DB tests

MIG-T01 up/down fresh schema in staging; MIG-T02 migrate anonymized current DB snapshot; MIG-T03 idempotent backfill double-run; MIG-T04 missing/duplicate data preflight FAIL; MIG-T05 no >2sec lock in migrations allowed during active traffic (profile/maintenance-specific); MIG-T06 API old+new binary compatibility through expansion; MIG-T07 crash halfway through backfill and restart; MIG-T08 DB restart/connection cut, SQLSTATE deadlock retry; MIG-T09 FK/CHECK/UNIQUE negative cases; MIG-T10 replication/backups/restore consistency. Publish EXPLAIN ANALYZE on catalog, jobs and owner-scoped queries.


---

<!-- Source: spec/08_INFRA_DEPLOY_CICD.md -->

# 08 — Production инфраструктура, CI/CD, hardening и безопасный релиз

## OPS-001. Production topology

- **Dev compose никогда не используется как prod.** Отдельные IaC manifests/Helm/managed service config; минимально допустимый надёжный deployment с HA: две API реплики каждой критичной службы в разных failure domains, минимум два worker экземпляра (safe leasing), multi-AZ PostgreSQL primary+replica/failover или managed HA и offsite backup. Если бюджет допускает только один VPS, официальная матрица SLO/DR и single point of failure помечается `NOT MET`, «полный high-availability production» запрещён.
- Gateway/reverse proxy HTTPS (ACME/cert rotation), one explicit internet ingress, no public PostgreSQL/Redis/internal/Admin ports, private service subnet, deny-all+allowlist egress to named dependencies, TLS internally, OIDC SSO private operator access.
- Separate environments staging/prod with distinct secrets/domains, database identity, storage, IAM. Staging copy anonymized; backup read access not granted to CI job unnecessarily.
- DNS, CDN, WAF, persistent connection budget, static assets from object storage, health checks, alert endpoint beyond primary infrastructure. Rate limiting also protects password hashing, expensive catalog, external integrations.

## OPS-002. Container and runtime

- Multi-stage, lockfile `uv sync --frozen`, final nonroot UID/GID, drop capabilities, `no-new-privileges`, read-only root FS with explicitly writable tmp if needed, seccomp baseline, resource requests/limits, pids, restart policy, graceful shutdown/drain, predictable startup.
- Pin base image by digest not `:latest`, vulnerability scan in CI, verify signed provenance or trusted registry, generate SBOM, maintain dependency update program; run `uv lock --check` or reproducible install. No cleartext secret embedded in image/layer or public Compose.
- No migrations at API container start. One-shot migration job with exclusive lock, rollback plan, preflight report and maintenance coordination.
- Worker separates tasks from HTTP (no background tasks per FastAPI lifespan); each job claims `SKIP LOCKED` lease and uses fencing/version to prevent stale acknowledgments.
- `/live`: process heartbeat only, no DB dependency. `/ready`: DB ping, pool, critical schema readiness, worker service SLI measured separately; do not require Admin for B2B read API readiness when not critical. Health routes must not reveal schema details/credentials publicly.

## OPS-003. CI gates before merge

1. Ruff/formatter/check type system (`mypy` or `pyright`), import compile, `uv lock --check`, security lint.
2. Full unit tests by service (all discovered, no selective -k substitution), coverage gate on critical paths e.g. >=90% branches on inventory/order/moderation business transitions **plus** mandatory tests (coverage alone insufficient).
3. Real DB integration with PostgreSQL service containers and isolated schemas, migration smoke, concurrency and timeouts; contract tests against current `contracts/*.openapi.yaml`/JSON Schema, producer/consumer samples.
4. SAST/secret scan, dependency vulnerability scan (severity policy: no exploitable Critical/High without signed time-bounded exception), container scanner, IaC scanner, license audit/SBOM. Require review of new critical dependency/security baseline.
5. E2E flow and short load smoke on staging, no production secret use in PR builds; only trusted branches can release.
6. Signed reproducible artifacts: manifest with git SHA, tested build digest, contract revision/hash and migration heads. Two-person review for migrations, auth, payments and role policy.

## OPS-004. Deploy and rollback

- Immutable image build -> staging -> smoke/integration/fault subset -> sign-off -> canary 1%/5%/25%/100% traffic with observation windows and explicit auto rollback thresholds (5xx, p95/p99, queue lag, integrity alerts).
- Run compatible `expand` migration before releasing new code. Workers canary separately; confirm old/new event schema compatibility; disable legacy inv write endpoints before switching.
- Deploy failure rolls back **code** only when DB backward compatible; otherwise stop writes and use forward fix with incident commander approval, not undocumented downgrade.
- Full audit of release, audit event for manual interventions, incident on rollback, frozen write feature flag for order/stock actions, healthy fail-open only for public read endpoints when explicitly safe.

## OPS-005. Capacity/performance

- Workload characterization: number sellers/products/SKUs/orders/cart operations, search/filter mix, concurrent checkout, peak burst, external service latency. Define baseline numeric requests/sec in release config (`capacity-profile.yaml`) before perf tests.
- Catalog: move filtering/sorting/pagination to indexed SQL, EXPLAIN ANALYZE, optional PostgreSQL FTS/search index; never `.all()` then Python filtering on unbounded catalog. Query limits, sort allowlist, max page=100, safe indexes, prepared SQL.
- Connection pools across N API replicas+workers satisfy capacity formula `Σ(max_connections app pools) + maintenance_headroom < DB max_connections`. Side-effects bounded by worker concurrency, rate limits and downstream timeouts.
- Graceful degrade via 429/503 with retry and `202 PENDING` only for persisted operation; circuit breaker cannot synthesize success.
- Load test >=2x forecasted peak, >=3x expected dataset, at least 24h soak, injected slowness and disk/WAL pressure; establish p95/p99 measured profiles before GO.

## OPS-006. Secrets, filesystem, network proof

- Build smoke rejects `postgres/postgres`, known dev secrets, missing auth public keys, `DEBUG=true` in prod; processes fail-fast.
- External port scan verifies only 443 (and controlled management) exposed. Admin requires VPN/IP allowlist+SSO MFA; private service origins inaccessible from public internet.
- Encrypted transport, DB schema permissions, no root container; secrets rotation tested before release, emergency revoke known documented.

## OPS-007. CI artifact requirements

A PR cannot merge without status pass; every rollout records `ci_run_id`, `image_digest`, `alembic_version`, `contract_hash`, `rollback_manifest`, canary dashboards, operator sign-off. Security/IaC exception has owner, severity, exploitability, expiry and compensating control; P0/P1 business correctness cannot be waived for full release.


---

<!-- Source: spec/09_BACKUP_DR.md -->

# 09 — Резервирование данных, аварийное восстановление и RPO/RTO

## DR-001. Объекты данных и модель отказов

Back up B2B/B2C/Admin DB clusters, PG WAL/base backups, object storage with media artifacts, secrets/keys references, IaC and migration manifests, configuration snapshots excluding cleartext secrets. Redis ephemeral and не содержит source-of-truth. Угроза: процесс умер, primary lost, disk corrupted, operator drop/truncate, ransomware/компрометация, регион недоступен, recovery трех баз на разные моменты.

## DR-002. Политика и измеримые цели

- Target primary DB **RPO <=5 минут** при потере всего primary site, **RTO <=60 минут** для критичных write operations **только при инфраструктуре, способной это обеспечить**; process failover RTO <=5 мин. Эти цифры — требования к выбранному deployment, не обещание, что один VPS/реплика дают их.
- Для локальной транзакции с подтверждённым DB COMMIT должна выполняться DB durability на surviving storage/WAL; асинхронная offsite реплика может терять последние минуты при региональном отказе — **невозможно обещать нулевую потерю** без дополнительной синхронной репликации/цены доступности.
- Base backup >=daily, WAL continuously archived to encrypted offsite bucket, retention default 30 days PITR + monthly immutable copies 3–12 months (конкретный срок утвердить с legal/product), separate account/region, keys not stored in same storage bucket. Enforce retention lock/immutability where provider supports it.
- Backup verify <=24h (archive healthy, manifests/checksums); restore rehearsal monthly and after backup topology changes, quarterly full DR role-playing. Measured actual RPO/RTO, signed evidence and last successful timestamp visible on dashboard; missing recent backup blocks risky deploy.

## DR-003. Техника PITR

- Использовать managed PITR либо pgBackRest/Barman с basebackup+WAL; простой `pg_dump` не заменяет WAL PITR. `pg_dump` может быть дополнительным логическим экспортом, но не единственным способом достичь target RPO.
- Standby из реплики не заменяет независимую backup; logical replication или snapshot не заменяют immutable offsite copy.
- Validate WAL timeline continuity, latest archive timestamp, storage size/budget, corruption checks and restoring into isolated infrastructure. Restore drills не воздействуют на реальные prod secrets/endpoints.
- Включить alert при archive lag >2 мин (engineering threshold, tuning after validation), backup failure 1 cycle, old verified restore >30 дней, low disk and failed encryption key access.

## DR-004. Восстановление и cross-service reconciliation

1. Incident commander переводит write APIs к безопасному read-only/fail-closed режиму, фиксирует incident/timestamp и freeze on external side effects; отключает старые workers, сохраняет доступные логи/event IDs.
2. Выбрать recovery point/time and snapshot set. Три независимые базы могут восстановиться на несовпадающие LSN/time — считать их **временно несогласованными** до reconciliation.
3. Восстановить isolated/staging volumes под новыми credentials; проверить checksum/PG integrity/migration heads and configuration, применить **только совместимые** миграции.
4. Внутри B2B проверить stock vs reservation_lines, lifecycle statuses and ledger; B2C checkout/order vs B2B lifecycle, Admin ticket/decisions vs B2B product revisions, B2C catalog projection vs B2B; выявить missing or duplicate events.
5. Повторить outbox/inbox и safe idempotent request with exact IDs/versions; неизвестные эквайринг-платежи сверить с provider (if present) **до** любых возвратов/списаний. Невосстановимые/спорные случаи вывести на manual incident queue. Не создавать «компенсацию» с новым random order_id.
6. После подписанного release invariant report, role/access tests, probes, canary write разрешить обработку; далее постепенно расширять трафик и наблюдать.
7. Составить postmortem без blame с impact window, actual RPO/RTO, data corrections, action items.

## DR-005. Неприемлемые варианты

- Docker volume как единственная копия; `docker compose down -v` в окружении с реальными данными.
- Backup на том же единственном VPS без независимой копии; backup пароль рядом в репозитории; любой restore без тестирования.
- Утверждение «RPO=0» из наличия WAL без подтверждённой репликации/реального измерения.
- Возобновление при расхождениях после восстановления B2B и B2C из разных временных точек.

## DR-006. Приёмка

DR-T01: delete/wipe only **isolated staging** DB and restore from offsite PITR; DR-T02: recovery exact chosen time ±RPO; DR-T03: simulate loss latest WAL/backup and alert; DR-T04: restore one DB ahead/behind others and reconcile without duplicate stock; DR-T05: outage database + worker recovery no lost committed order; DR-T06: backup credentials compromised, revoke without losing ability to restore; DR-T07: verify encryption+retention+immutability; DR-T08: published RTO/RPO measured and signed. Failure to restore in target time => NO-GO.


---

<!-- Source: spec/10_OBSERVABILITY_RUNBOOKS.md -->

# 10 — Наблюдаемость, SRE, эксплуатационные процедуры

## OBS-001. Three pillars + audit

- Structured JSON logs: timestamp UTC, level, service, version, region, trace_id, span_id, request_id, principal type, operation_id, `order_id`/`event_id` pseudonymized where possible, error_code, duration_ms, dependency. **Запрет** токенов, cookies, password hashes, raw PII/address, payment card details, secrets, HTTP Authorization.
- Metrics (Prometheus/OpenTelemetry): per-route request latency histogram and counts (`method/path/status`, no arbitrary UUID label), `http_5xx`, `auth_denied`, `db_pool_in_use/wait`, `db_locks/deadlocks`, `outbox_pending/oldest_age`, `inbox_conflicts`, `worker_attempts/dead/retries/lease_expiry`, `checkout_pending/oldest_age`, `cancel_pending`, `fulfillment_pending`, `moderation_pending/stale_decisions`, `inventory_invariant_violations`, `reconcile_diff`, `backup_last_success`, `wal_archive_lag`, `restore_last_verified`.
- Distributed traces with W3C traceparent propagates over service HTTP/outbox; event carries correlation_id, delivery span linked via event ID; asynchronous workflows sampled reasonably, error paths always kept within privacy constraints.
- Immutable admin audit trail and access audit for backups and sensitive operations, secure log retention. Audit not replaced by standard debug logs.

## OBS-002. Readiness, liveness, synthetic checks

`/live`: ASGI process alive (no DB calls). `/ready`: DB and schema reachable, ability to do lightweight SELECT; dependency checks necessary for write/read correctness; distinct worker `/metrics` and heartbeat. Worker dead should trigger alert even when API healthy. External synthetic tests: buyer catalog, seller restricted route, private moderation under synthetic identity (never public), non-mutating DB and API probes. Avoid synthetic checkout in production unless known isolated test accounts and designated non-real inventory.

## OBS-003. Alert policies (initial thresholds, tune against baseline)

| Alert | Condition | Priority | First action |
|---|---|---|---|
| Inventory mismatch | any confirmed SKU discrepancy | P0 | freeze affected SKU writes, page on-call |
| Orders orphan | any durable B2B active reserved without B2C committed/pending intent beyond grace | P0 | reconciliation + no blind release |
| Backup/PITR unsafe | WAL archiving stopped >5m or no verified backups within 24h | P0 | block risky deploy, incident |
| Auth bypass indicators | unscoped internal call success / admin impersonation | P0 | revoke tokens, freeze admin writes |
| Outbox oldest | >120s on critical event or >1000 pending | P1 | inspect worker lease/network/DLQ |
| Checkout/Cancellation stuck | age>5m or counts rapidly increasing | P1 | inspect downstream status/retry, manually reconcile |
| Fulfillment delayed | pending>5m after delivery proof | P1 | verify B2B reachability, rerun same id |
| DB capacity | >80% connections for 5m, disk <20%, long lock >10s | P1 | scale/throttle, query review |
| API SLO burn | sustained 5xx/p95 SLO burn windows | P1 | rollback canary / fail safe |
| DLQ>0 on business-critical event | first confirmed occurrence | P1 | root-cause, manual replay gated |

Escalation: primary on-call acknowledges in <=5 min for P0, secondary in <=10 min, incident commander appointed; escalation mechanism must have out-of-band failure path. Thresholds engineering defaults and require tuning on actual load.

## OBS-004. Operability и support

- All queued jobs show state, attempts, last_safe_error, lease, next_retry_at, last_event_id in protected operator UI. Manual replay only same event/order_id with approval and audit.
- Support view displays B2C Order snapshot, B2B lifecycle read-only, saga state, last successful/event timestamps, no raw secret/PII by default. Investigate by correlation id and immutable audit log.
- Dashboard for availability, dependency, queue lag, stock consistency, moderation SLA, backup status, CPU/memory, storage, DB, users impact, canary release. Each metric has runbook link and responsible team.
- SLO reviews weekly, error budget policy: if exhausted freeze nonessential releases until improved. Every P0/P1 postmortem with repro steps, missing control analysis, owner/date and closing evidence.

## OBS-005. Incident flow

Detection -> classify severity + affected assets -> freeze unsafe write routes if needed -> preserve evidence -> confirm live DB state under read-only credentials -> coordinated recovery/replay -> reconciliation tests -> staged unfreeze -> postmortem. For P0 security compromise revoke secrets and isolate network, do not publicly expose sensitive forensic artifacts. For suspected data loss, never overwrite latest available backups before preserving immutable copy.

## OBS-006. Tests

OBS-T01 failed DB causes /ready 503; OBS-T02 worker silently dies -> alert; OBS-T03 poison outbox gives DLQ+alert and does not starve other events; OBS-T04 2 worker replicas simultaneously claim without duplicate; OBS-T05 incident alert ack routing tested; OBS-T06 logs never emit tokens/PII; OBS-T07 trace correlates checkout reserve/cancel; OBS-T08 reconciliation seeded anomaly detection.


---

<!-- Source: spec/11_PAYMENTS_DELIVERY_AND_BUSINESS.md -->

# 11 — Product completeness: payments, shipping, refunds, seller settlements, compliance

## BUS-001. Неочевидный пробел текущего состояния

Обнаруженный аудит не подтвердил реального платежного провайдера, доставки с доказательством исполнения, фискализации, возврата платежей, расчётов с продавцами, customer support и legal data policies. `PAID`/`DELIVERED` enum в коде **не доказывает**, что деньги получены/товар доставлен. Для «полного production marketplace» бизнес обязан утвердить, какие из перечисленных сценариев входят в go-live; обещать их без реализации и верификации нельзя.

## BUS-002. Gate запуска по денежным операциям

**Вариант А (ограниченный запуск):** продажи без online card capture (например, offline invoice/COD там, где это законно и допустимо по продуктовым требованиям) — online pay controls скрыты/feature-flag disabled, `payment_status=NOT_REQUIRED` или `PENDING_OFFLINE`, действия `mark_paid` доступны только уполномоченному финансовому оператору с доказательством оплаты, audit и dual control на значимые суммы. Платформа не обещает платежи через неработающий интерфейс. Это не полный production онлайн-платежей.

**Вариант B (полный online marketplace):** отдельный PSP integration проект с approved provider, contractual/legal compliance и тестами ниже. Решение утверждается владельцем до full GO. Ни один статус PAID не меняется при callback browser/user input.

## BUS-003. PSP интеграция — обязательные контракты при Варианте B

- `payment_attempts`: payment_id, order_id, provider, external_payment_id unique, idempotency_key, amount_minor, currency, state (`CREATED/AUTHORIZED/CAPTURED/FAILED/REFUNDED/...`), authenticated webhook event ids, timestamps and reconciliation state. Не хранить PAN/CVV; использовать hosted checkout/provider tokens, PCI scope минимизировать.
- Authorization/capture/refund server-to-provider with idempotency, signed webhooks with timestamp skew/replay controls, IP alone insufficient; verified signature, event uniqueness and amount/currency/order matching. Provider webhook is *at least once*, persisted inbox. Browser redirect => pending, not paid.
- Inventory reserve before payment decision according to exact business policy; on payment failure/expiry trigger cancellation saga; if payment captured but stock reserve no longer valid, **не** скрывать случай: refund/review as durable job. Capture/refund exactly-once business effect under provider keys, daily provider reconciliation, settlement/disputes operations, incident runbooks.
- Client flow must state expiration, authorization/capture window and late webhook behavior. Business owner approves when cancellation is forbidden, when refund is automatic/manual, and seller payout timing. Cross currency/tax/commissions handled via financial ledger, not mutable order_total alone.

## BUS-004. Delivery/logistics

- Logistics owner chooses: in-house operator, carrier integration, or manual controlled workflow. Tracking events authenticated, delivery proof immutable (carrier reference, signature/hash, timestamp), transition delivery_confirmed -> durable inventory fulfill as in `spec/04`.
- Lost parcel/refund/partial delivery/returns demand separate state machine; for v1 without partial delivery, block unsupported partial shipment, instruct operator to use supported process and display accurate status. Tests with duplicate/out-of-order carrier webhooks, cancellation race and return after fulfill.

## BUS-005. Seller finance, privacy and legal readiness

- If sellers receive transfers, create seller balances/commissions/payout ledger with double-entry or auditable immutable transactions, PSP reconciliation and least-privilege authorizations. Нельзя отправлять выплаты как необратимый HTTP side-effect до durable accounting transaction.
- Tax/VAT/receipts/consumer rights/returns, handling of PII, age-related consumer rights, account deletion, retention and regulator incident notification depend on operating country and business model and require written legal approval. Это не гарантируется техническими тестами.
- Terms of service, privacy notice, cookie policy (if applicable), seller agreement, returns policy, user support and complaint SLA must be approved and shown to customers before taking real orders.

## BUS-006. Acceptance

For Option A: verify no accessible online payment endpoint, fake user `PAID` attempts 403, operator audit proof and offline reconciliation. For Option B: PSP sandbox signature validation, duplicate webhook, capture-response-loss, refund-response-loss, amount mismatch, replay webhook, delayed payment after cancelled reserve, provider outage, chargeback workflow, provider reconciliation and financial double entry; legal/PSP sign-off. For delivery: authenticated proof, duplicate webhook harmless, post-delivery stock decremented once; no silent success.


---

<!-- Source: qa/ACCEPTANCE_TEST_PLAN.md -->

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


---

<!-- Source: planning/DECISIONS.md -->

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


---

<!-- Source: planning/IMPLEMENTATION_PLAN.md -->

# Последовательность реализации до полного production, по шагам

## Правило исполнения

Каждый шаг: отдельный PR, runnable code+migrations+tests+feature flags+docs; до merge — строгие negative/concurrent tests, no regression по full suite; после — artifact commit SHA and sign-off. Точно изменяемые файлы уточняются с фактической структурой repo; перечисленные ниже — обнаруженные исходные модули из архива. **Никаких устаревших canon/OpenAPI к проверке не привлекать**. Контракты впервые создаются в `contracts` и затем версионируются в самом проекте.

### Этап 0. Immediate quarantine / риск P0

**STEP 0.1** Закрыть из внешней сети postgres/redis/admin и внутренние write endpoints. Разделить dev compose и production manifests; временно закрыть gateway на непроверенные handlers. Изменить `docker-compose.yaml`, `nginx/nginx.conf` (сейчас пуст), `Makefile prod`, IAM/firewall config. Acceptance `SEC-T07`, outside scan. DoD: none DB/admin/service internal accessible from public.

**STEP 0.2** Удалить или вернуть 410 + actual disabled из `services/b2b/src/api/routers/reservations.py` для legacy `/reservations`, `DELETE /reservations/{order_id}`, services methods `ReservationService.create/cancel_by_order` недоступны любому network client. Add unauthorized tests; acceptance SEC-T01/INV-T01. Не достаточно `include_in_schema=False`.

**STEP 0.3** Replace insecure `services/*/src/core/config.py`, JWT validation in `services/b2b/src/core/security.py`, `services/b2c/src/core/security.py`, `services/admin/src/api/deps.py`, `middleware/auth.py`; secret manager + fail-fast, service principals and RBAC. Add private Admin gateway/SSO MFA, no moderator ID spoofing; SEC-T01..08.

**STEP 0.4** DR baseline before touching data: offsite backups/PITR, full restore dry run and documented recovery, secret/key separation; `operations/BACKUP_RESTORE.md`; DR-T01..05.

**Gate 0:** P0-01,02,03,06 mitigated and evidenced; failure means continue work only in isolated staging.

### Этап 1. Database semantics and stock correctness

**STEP 1.1** Existing dataset preflight; add B2B Alembic migrations for `on_hand`, SKU constraints, lifecycle and reservation_lines, ledger and indexes. Files `services/b2b/src/models/sku.py`, `reservation.py`, new `inventory_order_lifecycle.py`, `reservation_line.py`, `inventory_ledger.py`, migrations, `sku_repo.py` and `reservation_repo.py`.

**STEP 1.2** Refactor `services/b2b/src/services/reservation_service.py` to single order_id locked lifecycle, tombstones on unreserve, canonical request fingerprint, sorted SKU locks, no timed deletion of business idem, consistent transaction boundaries; adjust `models/reservation_operation.py`, `unreserve_operation.py`, tests `services/b2b/tests/test_inventory_*.py`. INV-T01..12.

**STEP 1.3** Seller SKU stock update must use same locks/adjustment ledger. `services/b2b/src/services/sku_service.py`, `schemas/sku.py`, routers and DB CHECK. Validation `price>=0`, `stock>=reserved`; server-side image allowlist. SEC-T09, INV-T02/T09.

**Gate 1:** no negative stock, double reservation, late reserve resurrection or missing ledger in randomized PostgreSQL concurrent tests. Reconciliation actual SQL zero discrepancies.

### Этап 2. Durable asynchronous integration

**STEP 2.1** Unified `contracts/event-envelope-v1.schema.json`, `product-event-v1.schema.json`; `services/b2b/src/clients/moderation.py`, Admin moderation handler and Pydantic schemas. Producer->Consumer actual payload tests. EVT-T01 and no KeyError.

**STEP 2.2** B2B/Admin/B2C producer outboxes, consumer inboxes, event schema revision/ordering, retries with leasing, DLQ and per-aggregate versions. Existing `services/b2b/src/models/outbox_event.py`, `repositories/outbox_event_repo.py`, `services/b2b/src/main.py`, `services/b2c/src/main.py`, new worker entrypoints `src/workers/*`, `inbox` models and migrations; move **all** product/moderation/catalog remote writes out of pre-commit service code: `product_service.py`, `sku_service.py`, Admin `moderation_service.py`, clients. EVT-T02..07.

**STEP 2.3** Admin completeness: `services/admin/src/services/moderation_service.py`, `repositories/moderation_repo.py`, models and migrations, currently empty `api/routers/auth.py`, `products.py`, `sellers.py`, `models/audit_log.py`, add ticket CRUD/claim/release/heartbeat/decision, SSO/RBAC and audit. EVT-T08..12. Verify create product→Admin→B2C, edit/delete + delayed events.

**Gate 2:** no lost product event after DB rollback/crash; claims secure, outbox queue drains with 2+ workers; blocked SKU unsellable.

### Этап 3. Order/checkout and fulfillment

**STEP 3.1** B2C checkout intents durable lease/fencing and order status machine. `services/b2c/src/services/order_service.py`, `models/order.py`, `repositories/order_repo.py`, `api/routers/orders.py`, new `checkout_operations` route, migrations. Remove ambiguous final success under timeout; ORD-T01..05.

**STEP 3.2** B2C durable cancellation jobs and B2B tombstone linked to B2C final ack; compensate only if still valid, no creating order after COMPENSATING; same source files/order saga worker. ORD-T06..07.

**STEP 3.3** Authenticated delivery operation and separate fulfill worker; wire existing `retry_pending_fulfillments` to live job scheduler, extend persisted state/backoff, implement `DELIVERY_FINALIZING`; ORD-T08..09. Payment scope per `spec/11`.

**Gate 3:** repeated checkout/order deliveries, cancel and fulfill fault tests no orphan/duplicate; financial mode/logic never fakes PAID.

### Этап 4. Runtime, API, performance, security

**STEP 4.1** Replace old API definitions with `contracts/http-*.openapi.yaml` as new sole contract; implement missing public/owner-scoped endpoints, standardized errors, session lifecycle; CI `openapi diff`. `services/*/src/main.py`, all routers/schemas, shared utilities. API-T01..04.

**STEP 4.2** Move catalog filters into SQL and add indexes, paginate by cursor, load/capacity test. `services/b2b/src/services/product_service.py`, `repositories/product_repo.py`, B2C catalog adapter and migrations. PERF-T01..02.

**STEP 4.3** Harden deploy: nonroot digest-pinned image Dockerfiles, production IaC, ingress TLS, resource limits, no startup migrations, private networking, worker autoscale bounded. `services/{b2b,b2c,admin}/Dockerfile`, CI manifests, `Makefile`, prod IaC. OPS-T01..04.

**STEP 4.4** Metrics/traces/log redaction, readiness, alerts, incident support, data retention, secret rotation; `services/*/src/main.py`, shared middleware, workers/repo and operations runbooks; OBS-T01..08.

**Gate 4:** real environment no public data ports, correct RBAC/HTTP error envelopes, SLO goals load/soak, security scans/pentest, operator alert and DR drill pass.

### Этап 5. Full release and non-code blockers

**STEP 5.1** Validate real product scope: PSP and refunds, logistics, seller payouts, legal policy; if full online marketplace required, implement and certify BUS-T01..03. No external money flow before evidence.

**STEP 5.2** Run all `qa/ACCEPTANCE_TEST_PLAN.md`, live contract diffs, restore to isolated site, rollback drill, 24h soak and 2x load; sign-off `operations/GO_LIVE.md` including evidence links per risk. 1% canary -> 5% -> 25% -> 100%; abort on invariant/security/backup alerts.

**STEP 5.3** Post-launch: continuous reconciliation, SLO reviews, regular restore drills, planned secrets rotation, weekly risk review and incident simulations; no return to unmonitored/untested manual state.

## Recommended sequencing

Implement one step at a time, verify no regression, then proceed; avoid massive rewrite. For each step create `changeset.md` detailing schema effect, backward compatibility, rollback, test IDs, risk IDs, owner, exact CI logs and deployment proof. New paths/modules listed above are **proposed additions**, not assertions that these files already exist.


---

<!-- Source: operations/GO_LIVE.md -->

# Production GO / NO-GO protocol

**Policy:** Всегда NO-GO при любом незакрытом P0/P1, недоказанной сохранности заказов/денег, проваленном DR test, публичной неавторизованной модификации, неконтролируемом stock mismatch, отсутствии critical alert или обязательном для бизнеса платеже без проверенного PSP. Для «полного production» P2 закрываются, а узкая business scope оформляется документально.

## Подписи/инфраструктура

- [ ] Назначены product owner, tech lead, security owner, SRE/on-call, DBA, incident commander и backup delegate; контактные каналы реально протестированы.
- [ ] Все O-01..O-12 из planning/DECISIONS.md одобрены либо документирована явно урезанная область запуска, пользователи не вводятся в заблуждение.
- [ ] Зафиксированы commit SHA, image digests, contract hash, DB migration heads, list of feature flags и rollback manifest.
- [ ] Public ingress только TLS gateway, Admin private/SSO MFA, DB/Redis/internal routes из интернета недоступны; external scan evidence.
- [ ] Secrets random, independently scoped, stored/rotated in vault, no defaults, no source leaks. Network role and DB privilege checks PASS.

## Correctness and functionality

- [ ] Product CRUD -> moderation ticket -> claim+decision -> B2B -> B2C visibility E2E PASS and revision conflict handling.
- [ ] Checkout/cancel/fulfill E2E and compensations PASS with 2+ workers, DB loss, network timeouts, ACK loss; 0 orphan / 0 double effect.
- [ ] `reserved_quantity = SUM(active lines)` everywhere, no negative price/on_hand, no seller update below reserved.
- [ ] Reject forged moderator/owner/service identities, negative body, hidden legacy inventory endpoints removed.
- [ ] Consumer/producer JSON Schema and live OpenAPI vs contracts diff 0; new API version exclusive authority.
- [ ] All enabled endpoints implement RBAC, bounded pagination, stable error envelope and idempotency semantics.
- [ ] Payment/delivery/refund/settlement mode explicitly approved; no fake `PAID`, `DELIVERED`.

## Quality and operational readiness

- [ ] Full all-service pytest/integration/contract/fault suites green, no skipped release-critical tests; reports attached.
- [ ] 2x peak load / 3x data volume / 24h soak meet agreed p95/p99/error budgets; no OOM, deadlocks, queue accumulation.
- [ ] No unaccepted Critical/High SAST/DAST/container/dependency findings, manual security testing documented.
- [ ] Schema upgrade on current-like snapshot PASS, migration preflight/backfill and rollback compatibility PASS; separate one-shot job.
- [ ] Outbox/inbox retries, DLQ, reconciliation and protected manual replay verified; actual alert received by on-call.
- [ ] Offsite encrypted immutable PITR backup OK; clean-room restore **performed**, cross-DB reconciliation and measured RPO/RTO within target, last drill recent.
- [ ] Logs/traces/metrics/audit/alerts active; secrets/PII redaction and security event monitoring PASS.
- [ ] Incident, DR and backup runbooks reviewed; rollback and canary abort test PASS; support escalation staffed.

## Canary protocol and stop conditions

1. Freeze schema contract and flags, snapshot/backup verified. Canary 1% for measured observation, then 5%, 25%, 100% according to risk/traffic profile; worker rollout separately.
2. Monitor: DB errors, 5xx, p95/p99, outbox oldest age, checkout pending, cancellations, fulfillments, moderation backlog, stock reconciler, backup WAL, security denies.
3. **Immediate stop/freeze affected writes** on any confirmed inventory invariant violation, unauthorized write, data mismatch with actual impact, missing backup coverage, duplicated payment/fulfillment or poison events not recoverable. Preserve events; initiate incident not silent retries.
4. Auto rollback code if schema compatible; otherwise maintain safe read-only and apply reviewed forward-fix/restore procedure. After recovery sign checklist again.

## GO decision record (fill before release)

```text
Release ID: ___________________
Git SHA / image digests: _______
OpenAPI contract hashes: ______
DB migration heads: ___________
Security report / date: _______
Load/soak report / date: ______
Fault-test report / date: _____
DR restore report / actual RPO/RTO: ______
Unclosed P0/P1/P2: ____________
Business scope / PSP / logistics: ________
Tech lead: ______ Security: ______ SRE: ______ Product: ______
Decision: GO / NO-GO, timestamp: _______
```


---

<!-- Source: operations/INCIDENTS.md -->

# Incident playbook: inventory, orders, auth, event backlog, production outage

**Applies to:** on-call/SRE, security, DBA, product owner; all commands are design-level, should be translated into approved stage-tested tool scripts. Never use destructive tests in production. Never `docker compose down -v` with data.

## Universal response

1. Detect + page on-call, assign incident ID/severity and commander; record start time affected requests and last known consistent point.
2. Protect evidence (audit/outbox/inbox, request IDs, backups) and stop untrusted/unsafe traffic using scoped feature flag / ingress; avoid destroying partial orders.
3. Check readiness, DB storage/WAL, service principal/identity, worker lease and oldest queues. Always favor read-only SELECT queries first.
4. Choose recovery by state machine, use **same** event_id/order_id/request hash for replay; never patch stock directly. Require approved ledger adjustment if fixing data.
5. Verify invariant report and E2E smoke before unfreezing; report impact, owner, remediation, tracked incident follow-up.

## Scenario 1: SKU reserved mismatch / potential oversell

- P0: freeze writes for affected SKU/product; stop stock adjustments and new reserves, do not drop historical reservations.
- Read B2B `skus`, active reservation lines, lifecycle, ledger and B2C order state under consistent snapshot. Identify missing ledger/duplicate order or restore split-brain.
- Repair by audited reversible correction via inventory adjustment tool that takes locks and writes ledger, after security/DBA approval; do not `UPDATE stock=...` ad hoc.
- Run INV-T01/T06/T12 targeted staging repro with captured sanitized sequence. Reconciliation 0 discrepancies and incident-approved unfreeze.

## Scenario 2: Order stuck in `RESERVING`, `CANCEL_PENDING` or `DELIVERY_FINALIZING`

- Verify durable intent, worker lease/fencing and B2B lifecycle by signed read-only endpoint; inspect last remote call/ack.
- If ambiguous reserve, retry same reserve id; if compensation decided, retry `unreserve` with same order_id; `CANCELLED` from B2B -> close B2C; `FULFILLED` -> operator exception/returns, **not** silent cancel.
- Replay only after checking current lifecycle and conflicting worker; same exact key and payload. Manual operator action logged with actor and reason.

## Scenario 3: Event delivery or moderation backlog

- Check outbox worker and DB availability, service credentials, event schema, aggregate_version gap, DLQ. Pause only offending aggregate/event not all healthy work if safe.
- Fix consumer/schema, replay original event_id and version; validate Admin ticket exists and B2B applied decision, B2C catalog projection. Do not manually approve product by changing B2B `is_active`.

## Scenario 4: Auth bypass / compromised credentials

- Security P0: disable affected endpoint/account, rotate/revoke service tokens/keys, isolate network route, preserve access audit, identify timeframe and impacted objects. No broad cleartext logging of victims/tokens. Legal breach notification reviewed by security/legal.
- After fix test 401/403 for wrong identity and replay attacks, manual external surface review before reopening.

## Scenario 5: Backup/WAL/archive compromised / DB lost

- Halt high-risk deploy and write operations as appropriate; notify DBA/incident commander. Preserve latest safe backups (immutable if possible).
- Follow `operations/BACKUP_RESTORE.md` in clean isolated environment. Report actual RPO/RTO, cross-service reconcile, operational validation before promoting recovered instance.


---

<!-- Source: operations/BACKUP_RESTORE.md -->

# Backup/restore operational procedure (runbook template)

**Prerequisite:** chosen PostgreSQL PITR tooling/managed service configured. This is a procedure/checklist, not a magic executable command; actual `pgBackRest`/managed CLI depends on infrastructure and must be staged and reviewed. Never restore into the original production DB before preserving its available state.

## Daily control

- [ ] Check successful basebackup time and checksum, WAL archive continuous status/lag, backup storage size, immutability/object lock, encryption/key availability, offsite account permissions.
- [ ] Check alert for archive gap, backup failure, available disk and PITR retention coverage.
- [ ] Check latest restore drill timestamp and incident follow-up state; SLO dashboard has evidence.

## Monthly clean-room restore

1. Select arbitrary recovery timestamp inside recent retention range and expected committed business operations (order_id, SKU ledger entry, admin event) observed **before** incident simulation.
2. Provision isolated database environment with independent credentials/keys, no customer-facing ingress and no traffic routing. Verify backup manifests/integrity and recovered WAL timeline; restore three logical DB domains.
3. Log `restore_start`, `selected_recovery_point`, `WAL_latest_recovered`, `restore_complete` in UTC; compute actual data age/RPO and elapsed RTO. Do not invent success if lag exceeds target.
4. Run migrations-current and schema integrity read-only checks, critical constraints, cross-service reconcile B2B/B2C/Admin and durable outbox/inbox mismatch review.
5. Run operator read-only synthetic query and controlled mutation of synthetic tenant; assert owner isolation; ensure no external webhook/SMS/PSP side effects sent during drill.
6. Produce signed machine-readable report including failures, corrective backlog, RPO/RTO and next drill due. Delete test environment according to retention policy only after archiving evidence.

## Live disaster recovery

0. Executive/incident commander approves DR move. Freeze writes/PSP outgoing integrations; export untouched source state if available, preserve evidence.
1. Choose recovery point **based on business data consistency**, not only newest WAL; note cross-domain timeline gaps. Provision secure target and restore/backfill WAL.
2. Recover B2B then B2C/Admin or independent parallel restore with coordinated interface freeze. Before any replay, validate unique lifecycle ID, order status, product revision, and ledger totals.
3. Reconcile missing/in-flight orders, reserve/unreserve, fulfillment, moderation events using exact event IDs and signed service calls, not direct SQL side effects.
4. Validate auth/secrets and DB grants; rotate compromised keys; verify endpoint network isolation.
5. Canary write for designated synthetic/test tenant with available test SKU and no real payment; if invariants pass, controlled progressive traffic restoration.
6. Record actual time, impact, unresolved exceptions, permanent fixes and trigger next full test; confirm on-call/product/security sign-off.

## Critical failure cases

No valid offsite backup, no required WAL timeline, failed data checks, misaligned replay semantics or unknown stock ledger -> NO-GO; do not re-enable write traffic. Escalate to DBA/security/product for approved manual recovery.

