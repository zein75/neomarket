# NeoMarket Admin — consolidated production requirements

All narrative requirements in one file. Machine-readable contract, risk and acceptance CSV are separate files in the archive.



---

# SOURCE: MASTER_SPEC.md

# NeoMarket Admin Console — полная Production Specification

**Версия:** 1.0 • **Дата:** 2026-10-16 • **Scope:** Admin Frontend + Admin API + необходимые изменения B2B/B2C + workers/ops • **Статус:** TO IMPLEMENT, не deploy-ready.

## 1. Концепция, цели и границы

NeoMarket Admin — самостоятельное внутреннее рабочее место управления многосторонним маркетплейсом. Оно не заменяет B2B (владелец каталога и складских данных), B2C (владелец заказов покупателей) и платёжные/логистические сервисы. Админ-панель управляет **политиками, очередями проверки, решениями и операционными действиями** через авторизованные контракты. Ни одна операция не должна изменять чужую БД прямым SQL.

**Продуктовые цели:** один экран для каждой заявки с полным снапшотом; управляемая иерархия категорий с типизированными атрибутами; безопасная публикация/снятие товаров; продавцы, сообщения, жалобы, апелляции; машинно-проверяемые правила; объяснимые решения; аудит и возможность восстановить действия; без фиктивных данных. Масштабируемость: очередь 10^5+ тикетов и 10^6+ товаров не должна требовать загрузки всех записей в браузер.

**Обязательные модули:** обзор и очередь задач; модерация карточек и SKU; категории/атрибуты/бренды; правила и причины отклонения; продавцы и аккаунты; жалобы и апелляции; инциденты и массовые операции; журнал действий; состояние интеграций; пользователи/роли; настройки и мониторинг.

**Внешние зависимости, которые не считать готовыми:** идентификационный провайдер OIDC, MFA, загрузка файлов, KYC/проверка продавцов, платёжные disputes, логи доставок. При отсутствии договора/контракта для процесса: UI показывает `NOT_CONFIGURED`; пользовательские действия отключены; функции остаются BLOCKED, не симулируются.

## 2. Нефункциональные требования и обязательные инварианты

1. Любое решение по товару относится к **фиксированной ревизии снапшота**. Публикация устаревшей ревизии запрещена.
2. Для каждого редактирования администратором действуют: авторизованный principal, точная permission, `If-Match` или `expected_version`, `Idempotency-Key` для команд и атомарная запись аудита.
3. `moderation.status=APPROVED` само по себе **не означает**, что B2B обновил публикацию. Показать отдельные `decision_status` и `publication_status` до подтверждения потребителем события.
4. Ни одна межсервисная операция не совершается как ложная распределённая транзакция. Используются transactional outbox/inbox, уникальные event IDs, hash payload, retries, DLQ и reconciliation.
5. Категория/атрибут не удаляется физически, если на него ссылаются товары, заявки, правила или исторические события; применяется archive/deprecate и план миграции товаров.
6. Права проверяются **backend в каждой операции и на каждом объекте**; frontend hide/show — исключительно UX, не механизм защиты.
7. Значения денег — minor units + currency/Decimal, без float; не разрешать Admin редактировать подтверждённые платежи прямой правкой БД.
8. История решений и обязательные обоснования не подлежат незаметному редактированию и удалению.
9. Все изменения с эффектом на опубликованный каталог отображаются в журналах версий и безопасно инвалидируют кэш/поиск.
10. Высокорисковые действия (массовая блокировка, изменение правил публикации, массовый перенос категорий, выплаты) требуют двух независимых участников (`maker-checker`) и ограниченного по времени утверждения.

## 3. Роли и модель доступа

| Роль | Разрешено | Запрещено по умолчанию |
|---|---|---|
| `support_viewer` | Ограниченный просмотр обращений/публичных карточек | Решения, персональные сведения сверх задачи |
| `catalog_moderator` | Взять заявку, проверить поля, approve/reject текущей версии | Изменение ролей, правил, массовое снятие |
| `senior_moderator` | Escalate, hard-block по утверждённой политике, апелляции другого модератора | Одобрение собственной эскалации, назначение себе повышенных ролей |
| `taxonomy_editor` | Черновики категорий/атрибутов, запрос публикации изменения | Одобрение собственных критичных изменений |
| `taxonomy_approver` | Принятие/отклонение критичных изменений классификатора | Самоодобрение изменений |
| `seller_compliance` | Проверка продавца, ограничение при наличии оснований | Просмотр чужих платёжных реквизитов без отдельной роли |
| `trust_safety` | Жалобы, опасные/запрещённые товары, снятие с продажи, апелляции | Любое изменение денег |
| `operations` | Очереди/retry, безопасные бизнес-операции, incident view | Ручное назначение SUPERADMIN |
| `security_admin` | IAM, отзыв сессий, роли по утверждённой процедуре | Самоэскалация без второго подтверждения |
| `super_admin` | Управление политиками через защищённый workflow | Обход аудита, прямые изменения финансов/БД без контракта |
| `auditor` | Только чтение неизменяемых журналов и redacted evidence | Любые изменения |

Все роли — наборы атомарных permissions вида `moderation.ticket.claim`, `moderation.decision.approve`, `taxonomy.category.publish`, `seller.suspend`, `audit.export`; сервер хранит grants/scopes, staff identity и условные политики, включая separation-of-duties. `super_admin` не bypass без аудита. Все staff аккаунты проходят OIDC+MFA и управляются только через контролируемую IAM-систему.

## 4. Информационная архитектура и меню

`/dashboard` показатели по очередям, SLA, инциденты → `/moderation` очередь → `/moderation/{ticketId}` подробная проверка → `/products` все товары/публикации → `/products/{productId}` история ревизий → `/taxonomy/categories` дерево → `/taxonomy/categories/{id}` правила → `/taxonomy/attributes` → `/taxonomy/brands` → `/reasons` → `/sellers` → `/sellers/{id}` → `/reports` → `/appeals` → `/bulk-operations` → `/audit` → `/operations/events` → `/admin-users` → `/settings`.

Маршруты должны открываться по прямой ссылке; SSR/BFF проверяет реальную сессию до отдачи приватных данных; роли определяют разрешённые действия; интерфейс обеспечивает breadcrumbs, поиск, стабильные фильтры в URL, клавиатуру, пустые состояния, загрузку, обработку 403/409/412/429/503 и контекстные подсказки.

## 5. Модерация карточки товара (основной P0 модуль)

**Вход:** B2B генерирует `product.revision.submitted` с `product_id`, `seller_id`, `revision`, `snapshot_hash`, `submitted_at`, `actor_id`; Admin идемпотентно сохраняет заявку, immutable snapshot + ссылки на версии медиа. Различать CREATE, UPDATE, MEDIA_UPDATE, CATEGORY_CHANGE, RECHECK, REPORT, APPEAL. История каждой ревизии/решения сохраняется.

**Очередь:** приоритет, риск, дедлайн, категория, продавец, язык, источник, история; keyset пагинация и сохранение фильтров; автоматические правила назначения; ручной claim с lease + fencing token; списки `NEW`, `IN_REVIEW`, `WAITING_SELLER`, `ESCALATED`, `DECISION_PENDING`, `DECIDED`, `CANCELLED`, `STALE`.

**Экран ревью:** слева список заявок, центр изображение/галерея/поля карточки/SKU/документы с diff относительно опубликованной версии, справа чеклист и решения. Review checklist: идентичность продавца, корректность названия, запрет дубликатов, назначение категории, обязательные атрибуты, изображения и права на контент, описание/заявления/ценовые и налоговые поля при применимости, ограниченные товары, фрод-индикаторы. Каждое замечание привязывается к стабильному `field_path` и `sku_id`/`media_id`.

**Решения:** `APPROVE`, `CHANGES_REQUESTED`, `REJECT`, `HARD_BLOCK`, `ESCALATE`; для блока reason code + комментарий + field reports, для approval список пройденных правил, для hard-block обязательна elevated role. Система не допускает подписи решения по устаревшей ревизии, без claim lease или с чужим token. `DECISION_PENDING` до подтверждения обработки B2B. При противоречии B2B переводит заявку в reconcile/attention.

**Работающие инварианты:**
- `claimed_by` == текущий principal, `lease_token_hash` совпадает, `lease_expires_at > now`, `snapshot_revision == expected_revision`, `ticket.version == If-Match`.
- Выдача claim генерирует новый случайный token, срок lease и fencing counter; heartbeat продлевает только свою lease; release инвалидирует token; stale claimant никогда не может approve.
- Один `Idempotency-Key` + один `request_hash` → одно сохранённое решение; тот же ключ с иным payload → 409 `IDEMPOTENCY_CONFLICT`.
- Commit: audit + decision + outbox + перевод состояния в одной локальной транзакции; подтверждение B2B приходит асинхронно; решение, не дошедшее до B2B, не считается опубликованным.
- Защита from accidental double approval и out-of-order delivery должна быть на обоих сервисах.

## 6. Категории, атрибуты, классификаторы — полноценный управляющий модуль

**Владение:** каталог, категории, public visibility, валидация товаров и SKU принадлежат B2B. Admin является единственной разрешённой точкой управления классификатором через подписанные служебные команды/события; Admin хранит proposal/change request и аудит, но **не ведёт вторую независимую authoritative таблицу категорий**. Для UI Admin читает B2B через защищённый server-to-server client.

**Категория:** UUID, parent UUID|null, key, slug, локализованное name/description, display order, breadcrumb, status `DRAFT/ACTIVE/HIDDEN/ARCHIVED`, icon/media ref, SEO metadata, version, created_by, updated_by, effective_at, timestamps. Materialized path или closure table для предсказуемых рекурсивных операций; FK, уникальность sibling slug, отсутствие циклов. Счётчики подсчитываются асинхронно (всегда помечены `as_of`).

**CRUD:** создать черновик, редактировать, переименовать, drag-and-drop переместить с `preview`, активировать/скрыть/архивировать, slug redirects для публичных URL, сортировка, массовая реклассификация, импорт/экспорт с dry-run. Запрещены перемещение под своего потомка, удаление активной категории без migration plan, создание одинаковых slugs по утверждённой стратегии URL, потеря товаров при перемещении.

**Атрибуты и схемы:** `AttributeDefinition` с code, name, type (`string|integer|decimal|boolean|enum|multi_enum|date|reference`), unit, allowed/range/regex (ограниченные выражения), searchable, filterable, comparable, required, variant_dimension, PII flag, version; `CategoryAttributeRule` указывает scope категорий, порядок, conditional visibility/required, наследование и override. Attribute value сохраняется структурированно и валидируется сервером; нельзя принимать произвольный JSON в обход published schema.

**Справочники:** бренды с верификацией, нормализация производителя/свойств, единицы измерения, правила наименований, медиаполитики, запрещённые термины/политики. Изменения больших словарей через bulk preview, diff, validation report, approval, безопасный background job.

**Версионирование:** изменение опубликованной схемы НЕ изменяет автоматически старые одобренные карточки без назначенной политики миграции. До активации администратор видит count затронутых товаров, неправильные поля, необходимость повторной модерации, прогноз ссылок и изменение поисковых фильтров. Публикация через immutable schema version и отложенное применение. `PRODUCT_CATEGORY_CHANGED` / `TAXONOMY_VERSION_PUBLISHED` запускает переиндексацию и инвалидацию кеша через outbox/inbox.

## 7. Бренды, дубликаты, качество каталога

Справочник брендов, alias/синонимы, подтверждённое право на использование торговой марки, merge брендовых записей с сохранением редиректов и истории. Алгоритм поиска дублей использует GTIN/EAN/артикул/brand/model + нормализацию; автоматическое обнаружение — лишь рекомендация, не скрытый auto-ban. Каноническая карточка и seller offers должны иметь отдельную модель, если бизнес решит объединять предложения разных продавцов; до решения не делать silent merge чужих товаров.

## 8. Продавцы и соответствие требованиям

Карточка продавца: ID, публичный профиль, реквизиты согласно бизнес-политике, статус проверки, история, ограничения публикации, rate limits, обращения, предупреждения, moderation KPI, linked orders/returns (в рамках staff permissions). Принятие/блокировка продавца только с reason, policy version, version check, журналом и уведомлением. `ACTIVE`, `UNDER_REVIEW`, `RESTRICTED`, `SUSPENDED`, `TERMINATED` — отдельная state machine; `SUSPENDED` не уничтожает открытые заказы и резервы, требуется безопасная процедура выполнения обязательств перед покупателями.

Документы продавца загружаются через защищённое хранилище, антивирусную/типовую проверку, ограниченные подписанные URL, lifecycle retention. Для чувствительных данных — отдельные permissions, маскирование и audit-on-read. Без автоматического обхода проверки личности.

## 9. Жалобы, инциденты, апелляции

Жалобы на товар/продавца/изображение/нарушение правил поступают в triage, дедуплицируются, получают priority/SLA и доказательства с хешами. Рассмотрение: assign, request info, warn, unpublish, restrict, close, escalate. Отчёты пользователей защищены от раскрытия заявителя. Апелляция привязывается к первоначальному решению; reviewer не совпадает с автором решения. Отмена/коррекция решения только через новое audit event, а не изменение старой записи. Аварийное снятие товара (safety hold) отделено от окончательного решения и имеет авто-expiration и maker-checker для удержания дольше предела.

## 10. Безопасность Admin

OIDC Authorization Code + PKCE на server-side BFF, state/nonce, exact redirect allowlist; MFA/step-up для чувствительных операций, проверки issuer/audience/exp/nbf/jti и групп из доверенного провайдера; устойчивый principal mapping для строкового `sub` (не предполагать UUID). `HttpOnly; Secure; SameSite=Lax/Strict; __Host-` cookie непрозрачной серверной сессии, отзыв, idle/absolute TTL. API полномочия по роли, объекту, региону и действию, запрет mass assignment, pagination/rate-limit, CSRF, security headers enforcing CSP, контроль CORS. Admin не должен быть доступен в обход BFF/приватного gateway.

Audit с PII-redaction, read/audit logging, tamper-evident integrity и offsite backup; retention schedule зависит от юрисдикции и договоров и требует отдельного согласования. Изменение ролей, массовые публикации/блокировки и изменение политик — step-up MFA и dual control. Запрещены prod bypass через `X-Moderator-Id`, `NEOMARKET_DEV_OPEN_ACCESS`, локальные bearer token без IdP.

## 11. Административные операции и качество процессов

Dashboard: текущие очереди/SLA, загрузка модераторов, среднее время решения, неотправленные события, невалидные категории, ошибки публикации, дубликаты. Все метрики с provenance и `as_of`; нельзя вставлять вымышленную выручку/счётчики из Stitch. Bulk actions: selection snapshot, dry-run, количество допустимых/недопустимых, approvals, idempotent batch, per-item results и безопасная компенсация. Фоновый scheduler / outbox worker — отдельный deploy component, не привязанный к жизненному циклу каждого API replica.

## 12. API и протоколы

Целевой namespace `/admin/v1/*` для client BFF, `/internal/v1/*` для B2B/B2C. Каждая mutation принимает `Idempotency-Key` и `If-Match`/`expected_version` по смыслу; все response в `application/json`; стандарт ошибок `application/problem+json`: `type`, `title`, `status`, `detail`, `code`, `instance`, `request_id`, `retryable`, field errors. Cursor pagination — keyset (stable sorting by created_at,id); фильтры валидируются, maximum page size 100. Мультисервисные команды отражаются как `202 Accepted` с `operation_id`, а клиент читает `/admin/v1/operations/{id}`. Контракты в `contracts/` являются **предлагаемыми**, не существующими endpoint'ами.

## 13. Публикация и индексация

B2B сохраняет одобренную ревизию при подтверждённой команде; активность товара, sku, категории, seller.status и индекса учитываются отдельными условиями. Публичная видимость равна утверждённому составному предикату, а не одной строке `MODERATED`. При изменении taxonomy/brand/mode B2B посылает события и обновляет projection B2C и search; пропущенные события выявляются reconciliation jobs.

## 14. Надёжность и данные

Transactional outbox/inbox с durable очередью, exponential backoff с jitter, DLQ, replay только после проверки причины; event version и correlation_id. DB backups/restore drills, отдельно защищённое хранилище аудита и документов, миграции expand/backfill/switch/contract; без деструктивной миграции без backout-plan. `at-least-once` доставка + бизнес-идемпотентность, не «exactly once across services». Monitoring: queue_age, oldest_pending_seconds, decision_to_publication_delay, DLQ count, 4xx/5xx, login failures, role changes, mutation conflicts. Alert thresholds определяются измеренными baseline/SLO.

## 15. Тестовая стратегия

Каждое требование связано с тестом и screenshot evidence. Необходимы unit, property-based, integration с PostgreSQL, migration upgrade/downgrade, contract testing B2B/Admin/B2C, конкурентные race tests, негативные permission tests, E2E Playwright на тестовых данных, visual regression по оригинальному PNG/HTML Stitch, WCAG2.2 AA, security, resilience/fault injection, load тесты, DR restore. Три независимых прогона после последнего изменения; скриншоты не обновлять автоматически.

## 16. CI/CD и staged rollout

GitHub Actions: formatting+typing+tests → PostgreSQL integration+migrations → OpenAPI breaking-change check → dependency/SBOM scanning → build signed/pinned Docker images → deploy ephemeral QA → Playwright/visual/a11y → review → staging migration dry-run → canary (по возможности) → production manual approval → smoke + monitoring window. На существующем VPS 1 vCPU/1GiB нельзя валидировать fullstack production нагрузку. Нужен staging сопоставимых сервисных границ и достаточных ресурсов. Секреты не хранятся в Git.

## 17. Политика завершения

**NO-GO:** нет OIDC+MFA, нет проверки ревизии/lease/idempotency, нет authoritative category management, не завершены publish propagation, нет рабочего Admin UI, critical tests skipped, нет восстановления аудита/БД. `PASS` только после устранения P0/P1 и прохождения gates, а не после формального закрытия задач. Все открытые внешние бизнес-решения маркируются `BLOCKED` и отдельно согласуются.

Смотри детальный реестр рисков, workflow, OpenAPI, план и матрицу приёмки в соседних файлах.


---

# SOURCE: audit/CURRENT_STATE.md

# Фактическое состояние NeoMarket Admin в исходниках 2026-10-16

**Метод:** выборочное статическое чтение сервисов и frontend в архиве `neomarket-full-audit-2026-10-16.zip`, просмотр исходного `docs/design-system/stitch/admin-panel/reference.png`, инвентаризация маршрутов и моделей. Число успешных PostgreSQL/E2E/нагрузочных тестов в этом аудите: **не подтверждено**. Нет доступа к рабочей production-инфраструктуре, поэтому runtime-гарантии не проверены.

## Confirmed inventory

| Подсистема | Файлы-источники | Факты |
|---|---|---|
| Admin Next.js | `frontend/apps/admin/src/AdminPage.tsx`, `app/moderation/page.tsx`, `app/login/page.tsx`, `middleware.ts` | `AdminPage.tsx` представляет короткую fail-closed заглушку; нет полноценной панели модерации и запросов BFF; login редиректит на внешний URL из env или сообщает, что OIDC не настроен; middleware обращается к внешнему session service, в архиве не обнаружен завершённый admin login/callback/session flow |
| Auth API | `services/admin/src/api/deps.py`, `core/config.py` | production JWT проверяется (issuer/audience/exp); поддержана ветка OIDC/JWKS + `amr` MFA; для `sub` используется `UUID(str(subject))`; это не универсально для OIDC; роль фактически проверяется как `moderator/admin`, а не per-permission. В development есть путь с доверенным `X-Moderator-Id`; он должен быть гарантированно недоступен в staging/prod |
| Категории | `services/b2b/src/models/category.py`, `api/routers/categories.py`, `services/category_service.py` | Категория: `id,name,slug,parent_id,is_active`. Есть list/get для продавца/public service (с service auth); записи/управления деревом Admin нет, category-detail placeholder возвращает `description=None`, `seo={}`, `meta_tags={}`, `image_url=None` |
| Товар | `services/b2b/src/models/product.py` | `category_id` пока nullable без ORM FK; товары имеют `images JSON`, `characteristics JSON`, `status` и `is_active`; отсутствует полноценная схема версий карточек и публикуемой ревизии |
| SKU | `services/b2b/src/models/sku.py` | price/stock/reserve DB-checks есть; мониторить миграцию с `stock` на `on_hand` и изменение опубликованного SKU |
| Moderation | `services/admin/src/api/routers/moderation.py`, `services/moderation_service.py`, `models/moderation.py` | Тикеты, листинг, claim/release/heartbeat, approve/block, причины отказа, audit events и события B2B есть. `DecisionRequest` содержит `claim_token`, `product_revision`, заголовок `Idempotency-Key`, но `decide_ticket` не сверяет первые два параметра с сохранённым snapshot/lease и возвращает заголовок как decision_id без стойкого request-receipt. Ревизии в `ModerationCard` не обнаружены |
| Очередь | `services/admin/src/repositories/moderation_repo.py` | offset-based пагинация base64 offset, жёсткий лимит 10k; сортировка `queue_priority,created_at` без стабильного tie-breaker по UUID; нужна keyset для больших очередей |
| Audit | `models/audit_log.py`, `api/routers/moderation.py` | Аудит с actor/action/entity/details; нет подтверждённого tamper-evident export, audit-on-read и политики retention. Листинг только базовый, offset pagination |
| Outbox | `models/moderation_outbox_event.py`, `services/moderation_service.py`, `main.py` | Есть outbox retries, DEAD, lease, `FOR UPDATE SKIP LOCKED`; worker создаётся в lifespan API → при нескольких инстансах/рестартах требуется более строгая топология, мониторинг и выделенный worker |
| Product event | `models/processed_product_event.py`, `services/moderation_service.py` | Есть receipt/idempotency hash, но требуется проверка неизменяемых ревизий, строгого ordering и восстановление пропусков |
| Другие admin-модули | `services/admin/src/api/routers/products.py`, `sellers.py`, `auth.py`, `services/auth_service.py` | На момент snapshot эти модули пусты; в `main.py` подключён только moderation router |
| Визуальный эталон | `docs/design-system/stitch/admin-panel/reference.png`, `source-official.html` | Макет содержит sidebar, KPI карточки, очередь тикетов, просмотр товара/изображений/SKU и панель решений; иллюстративные числа, названия и изображения не являются реальными данными |

## Самые значимые подтверждения

1. **P0 / fail closed by design:** публично пригодного Admin UI пока нет. Это безопасный временный режим, но не функциональный продукт.
2. **P0 / integrity:** `POST /admin/v1/moderation/tickets/{id}/decisions` принимает `claim_token` и `product_revision`, но непосредственная логика игнорирует их. Нужна БД-модель замка/ревизии и строгие сравнения при каждом решении.
3. **P1 / taxonomy:** нет CRUD категорий/правил/атрибутов Admin; нужно добавить с сохранением собственности B2B на каталог.
4. **P1 / security:** UUID-конвертация OIDC `sub` сломается при обычном непрозрачном строковом идентификаторе IdP. Нужно `(issuer,subject) -> staff_id UUID`.
5. **P1 / permissions:** role check не равен RBAC для управления политиками, каталогом, продавцами, аудитом и доступами.
6. **P1 / scaling:** offset pagination и лимит 10k недостаточны для большой очереди; snapshots и keyset обязательны.
7. **P1 / operation:** жизненный цикл outbox worker внутри API требует выделения, отдельно проверяемого отказоустойчивого запуска.
8. **P2 / source-of-truth:** текстовые/SEO атрибуты категории в API возвращают пустые placeholders; UI не должен показывать их как заданные администратором.

## Границы уверенности

- `CONFIRMED_SOURCE`: перечисленные факты из кода.
- `ARCHITECTURE_RISK`: последствия в гонках, расхождения после отказов, редактирование чужих объектов — требуют runtime тестов и adversarial проверки.
- `NOT_TESTED`: миграции/DR/performance/реальный OIDC/сквозная публикация/доставка сообщений — отсутствуют воспроизводимые результаты текущего аудита.

**Не путать:** `DecisionRequest` с полями не означает их серверную валидацию. `202 Accepted` не означает, что товар уже опубликован. Спецификация ниже определяет, как довести эти гарантии до production.


---

# SOURCE: architecture/DOMAIN_AND_DATA.md

# Domain model, data ownership and DB constraints

## Bounded contexts

- **B2B/Catalog** — категории, атрибуты, бренды, карточки/версии, SKU, seller identity/reference, public flags, search projection triggers.
- **Admin/Moderation** — immutable review snapshots, tickets, leases, decisions, blocking reasons, appeals, complaints, audit, workflow policy, admin operations and local outbox.
- **Admin/IAM** — staff principal mapping, role grants, MFA evidence/step-up, session metadata; primary identity remains external IdP.
- **B2C/Marketplace** — shopping/buyer orders, feedback/reports, user-facing display projections; Admin does not write B2C tables directly.
- **Media** — object storage, verified image scan/processing and immutable media version references (owner B2B/media service).

Admin reads cross-service data via constrained projections or server-to-server commands, not shared ORM joins across microservice databases. All `*.id` UUID are stable references; product revision is monotone integer in B2B. `external_subject` OIDC string is not forced to UUID.

## Entities (normative fields)

| Entity (owner) | Required fields | Invariants/indexes |
|---|---|---|
| `staff_principals` (Admin) | id UUID, oidc_issuer, oidc_subject, status, created_at | unique `(oidc_issuer,oidc_subject)` |
| `staff_grants` (Admin) | id, principal_id, permission, scope, granted_by, expires_at | no self-grant high privilege, audited |
| `moderation_tickets` (Admin) | id, product_id, seller_id, submitted_revision, snapshot_hash, kind, priority, state, version, created_at, deadline_at | unique `(product_id,submitted_revision,kind)` when appropriate; index `(state,priority,created_at,id)` |
| `moderation_snapshots` (Admin) | id, ticket_id, revision, snapshot JSONB, hash, media refs, policy_version | immutable, FK ticket |
| `moderation_leases` (Admin) | ticket_id PK, owner_staff_id, token_hash, fencing_version, expires_at, last_heartbeat_at | lease at most one owner per ticket, no plaintext token |
| `moderation_decisions` (Admin) | id, ticket_id, revision, actor, action, reason_ids, field_reports, comment, request_hash, idempotency_key, delivery_status, policy_version, created_at | unique `(actor_id,idempotency_key)` scoped, cannot edit/remove |
| `decision_outbox` (Admin) | id, decision_id, aggregate revision, payload, event_id, state, retries, next_retry_at, lease, created_at | unique event_id, durable retry/DLQ |
| `blocking_reasons` (Admin) | id, code, locale labels, severity, applicability, active, policy_version | code immutable, cannot delete referenced reasons |
| `complaints` (Admin) | id, source, reporter_ref, product_ref/seller_ref, category, state, priority, evidence_refs, SLA, created_at | protected reporter, reasoned lifecycle |
| `appeals` (Admin) | id, original_decision_id, claimant_ref, reviewer_staff_id, evidence_refs, state, outcome | reviewer distinct from original actor |
| `audit_events` (Admin) | id, recorded_at, actor, roles, action, entity refs, before_hash, after_hash, reason, request_id, correlation_id, redacted_details, integrity_hash | append-only access; off-site retention |
| `admin_operations` (Admin) | id, type, payload_hash, requested_by, approvals, status, item_results, started_at, finished_at | idempotency + maker-checker |
| `categories` (B2B) | id, parent_id, code, slug, labels, status, sort, path, version, redirect policy, timestamps | no cycles; unique canonical path; no hard delete with refs |
| `attribute_definitions` (B2B) | id, code, data_type, units, constraints, labels, version, status | codes immutable, typed data |
| `category_attribute_rules` (B2B) | id, category_id, attribute_id, required/conditional/variant flags, inherited, version | unique `(category_id,attribute_id,version)` |
| `taxonomy_change_requests` (Admin) | id, target refs, before_version, draft_payload, impact_summary, requested_by, approved_by, status | proposer != approver when sensitive |
| `brands` (B2B) | id, canonical name, aliases, verified status, version | normalized uniqueness, merge history |
| `product_revisions` (B2B) | id, product_id, revision, content, policy_schema_version, status, snapshot_hash, created_at | unique `(product_id,revision)` immutable |
| `product_publications` (B2B) | product_id, published_revision, visibility, visibility_reasons, updated_at | never publish unapproved revision |

## Mandatory database behavior

1. Timestamps UTC (`timestamptz`), no naive datetimes. Foreign keys, check constraints, uniqueness and indexes. Default-deny data exposures via response schemas (never expose raw ORM objects).
2. Each command uses optimistic concurrency (`version` monotonic / If-Match). Moderator claim additionally requires `SELECT ... FOR UPDATE` or atomic compare-and-set. Leases carry fencing sequence to defeat expired-client writes.
3. `decision` creation, audit append, outbox insert and state change in one Admin DB transaction; B2B applies event in separate transaction + inbox receipt in that same transaction. No distributed SQL transaction or direct remote writes before local commit.
4. Snapshot, decision, policy_version and product revision remain queryable for future appeals, including media versions. Redaction/deletion schedules must preserve legal rights and privacy obligations according to policy.
5. Taxonomy move/merge requires impact preflight, transaction-safe subtree update and relationship validation; large backfills run in batches with resumability/cursor checkpoints. Existing slugs redirected safely.
6. Historical stock and payment data never edited as side effect of moderation. Existing orders/returns are handled by explicit fulfillment/refund workflows.
7. Replay duplicate event → same durable result; replay same ID different hash → 409 + incident alert. Out-of-order revision → hold for reconcile, never blindly downgrade publication.
8. Use explicit service DB roles; migration role separate from runtime role. No one service allowed admin privileges over another database.

## Example state machines

### Ticket

`NEW -> IN_REVIEW -> (CHANGES_REQUESTED | DECISION_PENDING | ESCALATED)`; `CHANGES_REQUESTED -> WAITING_SELLER -> NEW` via new immutable revision; `DECISION_PENDING -> DECIDED` only after confirmed downstream projection; any open ticket may become `STALE` on superseding revision and cannot be decided; `ESCALATED -> IN_REVIEW` by appropriately privileged staff. `HARD_BLOCK` is a decision outcome, not the same as temporary visibility `SAFETY_HOLD`.

### Category

`DRAFT -> REVIEW_PENDING -> ACTIVE`; `ACTIVE -> HIDDEN` (hide public listing only with defined product impact); `ACTIVE/HIDDEN -> ARCHIVED` after plan, redirects and product reclassification; `ARCHIVED` not hard-deletable if used in history. New schema versions are immutable after activation. Exposed legacy `is_active` is projection during migration.

### Appeal

`SUBMITTED -> TRIAGED -> IN_REVIEW -> (UPHELD | OVERTURNED | PARTIALLY_UPHELD) -> CLOSED`; appeal outcome generates a new corrective decision/event, not mutation of old record. Two-person for high-risk reversals.

## Representative invariants in SQL form (design examples, not executable migration)

```sql
-- Design intent: reconcile table names with existing Alembic metadata first.
UNIQUE (product_id, submitted_revision, kind);
UNIQUE (oidc_issuer, oidc_subject);
CHECK (version >= 1);
CHECK (lease_expires_at > lease_created_at);
-- transactional command: UPDATE ... WHERE id=:id AND version=:expected_version
-- target rowcount must equal 1, else return 412/409.
```

Detailed expand/contract migration stages in `migrations/MIGRATION_BLUEPRINT.md`.


---

# SOURCE: architecture/WORKFLOWS.md

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


---

# SOURCE: architecture/OPEN_DECISIONS.md

# Open architecture/business decisions — must be approved, not guessed

| ADR | Decision required | Default safe implementation pending decision |
|---|---|---|
| ADR-ADMIN-01 | Real OIDC provider, MFA and step-up claims | Fail closed Admin auth; no local fallback |
| ADR-ADMIN-02 | Staff roles/scopes/org/regional separation | Least privilege; no publish/hard-block until role mapping signed off |
| ADR-ADMIN-03 | Exact moderation reason taxonomy and prohibited-listing policy | Require explicit reason; no automated hard block on heuristic alone |
| ADR-ADMIN-04 | Allowed status actions of an already published product being edited | Keep prior valid revision if safe, new revision pending; safety hold separate |
| ADR-ADMIN-05 | Slug uniqueness and public URL canonicalization across taxonomy | Prevent duplicate paths, hold move until redirect policy approved |
| ADR-ADMIN-06 | Category inheritance/override and grandfathered old products | Schema changes apply to new submissions; old products flagged for migration review |
| ADR-ADMIN-07 | Scope of seller compliance (country, documents, business onboarding) | No fake KYC verification; mark BLOCKED |
| ADR-ADMIN-08 | Appeal deadlines and independence requirements | Reviewer cannot be original decision actor; configurable policy |
| ADR-ADMIN-09 | Temporary safety hold expiry and irreversible block requirements | Short bounded hold, audit and escalation, no silent termination |
| ADR-ADMIN-10 | PII/evidence/log data retention and staff audit access | Data minimization + secure storage; legal signoff pending |
| ADR-ADMIN-11 | Threshold for two-person approval on bulk operations | Require approval for all high-impact writes until threshold approved |
| ADR-ADMIN-12 | Model of brand verification and duplicate product/offer grouping | No automatic irreversible merge |
| ADR-ADMIN-13 | Expected RPO/RTO/SLO, alerting thresholds and release capacity | Design monitoring, leave production readiness BLOCKED until measured |
| ADR-ADMIN-14 | Financial, refund, tax, logistics admin functions and jurisdiction | Read-only scoped views, no payment mutations until provider/policy agreed |

For each ADR record owner, date, considered alternatives, decision, consequences, schemas/tests affected and acceptance by responsible stakeholders. New components absent from Stitch need approved visual extension; do not invent and call it pixel-perfect to a nonexistent screen.


---

# SOURCE: contracts/EVENTS_AND_ERRORS.md

# API semantics, event contracts and failure behavior

## HTTP contract rules

- Base `/admin/v1` only for principal-bound clients; `/internal/v1` for signed services. Admin frontend always calls BFF; BFF calls Admin/B2B server-to-server.
- For mutating requests `Idempotency-Key` (UUID string) and `If-Match` where concurrency matters; return `409 IDEMPOTENCY_CONFLICT` on same key with different normalized payload.
- `202 Accepted` contains `{operation_id,status,resource_id?,request_id}`; it does NOT imply downstream publication success. Poll status endpoint or subscribe to authorised server event stream.
- Canonical JSON error `application/problem+json`: `type, title, status, detail, code, instance, request_id, retryable, errors?` (errors field redacted). Invalid input 422; stale ETag 412; conflict 409; anonymous 401; unauthorised 403; dependency 503; temporary limits 429 (+ Retry-After). Never 200 with `{success:false}` for real failures.
- Lists use keyset encoded opaque cursor with stable order `priority DESC, created_at ASC, id ASC`, filters and signed cursor policy if cursor state contains sensitive info; page max 100. `items,page{next_cursor,has_more}`. Immutable action records are never soft-overwritten.

## Event envelope v1

```json
{
  "event_id": "3b81acdc-5eac-4c18-8d94-a61f47fe99e4",
  "event_type": "product.revision.submitted",
  "event_version": 1,
  "producer": "b2b",
  "aggregate_type": "product",
  "aggregate_id": "9139bf92-a16b-43c5-a0f3-92e98103209a",
  "aggregate_version": 7,
  "occurred_at": "2026-10-16T12:00:00Z",
  "correlation_id": "4c15ac8e-dd61-4806-a1f1-a0cb204188e9",
  "causation_id": null,
  "payload": {
    "product_id": "9139bf92-a16b-43c5-a0f3-92e98103209a",
    "seller_id": "6fa3a884-bce1-4c05-bbc1-4bc26e793a99",
    "revision": 7,
    "snapshot_hash": "sha256:REPLACE_WITH_REAL_HASH",
    "snapshot_ref": "object-ref:revision/7"
  }
}
```

This is a **schema example with placeholders**; not an actual emitted production event. Define real media ref/aggregate authorization contract before rollout. Never dereference untrusted URLs for snapshot_ref.

## Required event types

- `product.revision.submitted.v1` → admin ticket submitted.
- `moderation.decision.recorded.v1` → audit/decision, not public publication.
- `moderation.decision.delivery_requested.v1` → outbound to B2B.
- `product.publication.applied.v1` / `product.publication.rejected.v1` → admin operation resolution.
- `taxonomy.category.created|updated|moved|archived.v1` → cache/index synchronization.
- `taxonomy.schema.published.v1`, `brand.merged.v1`, `seller.restriction.changed.v1`.
- `complaint.created.v1`, `appeal.submitted.v1`, `admin.operation.failed.v1`.

Choose a single exact naming convention in an ADR before implementation and don't silently mix dotted names with underscore legacy event types; introduce adapters only at the edge.

## Consumer contract

1. Validate signature/service identity, schema/event_version, timestamp window where applicable, aggregate ID and monotone version.
2. Calculate canonical payload hash. Insert inbox receipt `event_id` unique in the **same transaction** as business mutation. On duplicate with same hash, return previous response. On same event_id different hash, conflict+alert. On out-of-order event, buffer/reconcile and never roll back aggregate version.
3. Make outbox delivery at-least-once; worker may retry after crash. No optimistic `SENT` without verified HTTP ack.
4. Backoff+jitter; bounded attempts; DLQ with explicit policy and operator case. Manual retry permission-gated and audited.
5. Reconciliation periodically verifies Admin decisions versus B2B published_revision and B2C public projection, and resolves discrepancies with reversible remediation.

## Contract verification

- Generate admin/b2b/b2c OpenAPI from actual apps, compare to target, validate examples with JSON Schema/OpenAPI in CI.
- Consumer-driven tests for receipt/replay/version ordering/correlation and redaction; do not treat this document's proposed examples as current runtime behavior.


---

# SOURCE: design/ADMIN_UI_SPEC.md

# NeoMarket Admin UI — точная реализация по Stitch с реальными данными

## 1. Источник визуальных требований

Оригиналы в архиве source: `docs/design-system/stitch/admin-panel/reference.png` и `docs/design-system/stitch/admin-panel/source-official.html` (а также актуальные токены/документация). Скриншот показывает технический neo-brutalist dashboard: верхняя панель, левый sidebar, компактные технические метки, KPI-виджеты, список заявок, панель карточки товара, чеклист и заметные решения. 2x PNG соответствуют CSS-viewport меньшей ширины — сравнивать после нормализации pixel ratio.

**Правило:** PNG + HTML — композиция и визуальная основа, но содержат демонстрационные данные. Точные токены принимаются из утверждённого Design System source. Отсутствующие токены — предмет ADR; нельзя изобретать новые цвета и считать их эталонными.

## 2. Глобальный layout

- `AdminShell`: фиксированное приложение с вертикальным navigation rail, header, contextual breadcrumbs, быстрым поиском и account menu. Mobile — drawer, responsive grid, sticky action bar только с видимыми статусами.
- Global providers: authenticated principal + permissions; theme tokens; i18n; server-state cache keyed by principal/scopes; no persistent token in localStorage.
- `DataGrid`: cursor pagination, сортировки на сервере, filter chips в URL, bulk selection snapshot (не «все текущие DOM строки»), skeleton, empty/error, keyboard+screenreader controls.
- `StatusBadge`: palette/state text and accessible non-color signal. Async `operation_status` отдельный от `business_status`.
- `RequestErrorPanel`: 401/403/409/412/422/429/502/503 и request_id; retry только безопасных операций; при 409 сохранение введённых комментариев.
- i18n `ru-RU` first; даты timezone из настройки пользователя с UTC при экспорте; цены с валютой, без float.

## 3. Страницы и компоненты

| Route | Компоненты / операции | Требуемое доказательство |
|---|---|---|
| `/dashboard` | `QueueMetricCard`, `SlaTrend`, `WorkloadByModerator`, `PendingOutboxAlerts`, `CategoryHealth`; drill-down | Метрики из реальных агрегаций, c `as_of`, без hardcoded KPI |
| `/moderation` | `TicketFilterBar`, `TicketQueue`, `SortSelector`, `ClaimIndicator`, `BulkAssign`; deep links | keyset курсор; фильтры; rights; нет потери/дублей |
| `/moderation/[id]` | `RevisionHeader`, `ProductDiff`, `MediaGallery`, `SkuTable`, `AttributeChecklist`, `SellerRiskPanel`, `ModerationDecisionPanel`, `DecisionTimeline`, `ClaimTimer` | В настоящем браузере проверить approve/reject/stale claim, 202→publication confirmed |
| `/products` | `ProductsGrid`, `PublicationStatus`, `VisibilityReasons`, `RevisionTimeline`, `OpenReports`, `UnpublishAction` | Только реальный каталог, права и reason-coded actions |
| `/taxonomy/categories` | `CategoryTree`, `CategorySearch`, `CategoryInspector`, `CategoryWizard`, `MovePreview`, `ImpactReview`, `VersionDiff` | add, edit, activate, archive, cycle prevention, impacted products |
| `/taxonomy/attributes` | `AttributeDefinitionTable`, `SchemaRuleEditor`, `InheritancePreview`, `ConstraintTester` | type validation + category rules in B2B |
| `/taxonomy/brands` | `BrandRegistry`, `AliasEditor`, `MergePreview`, `ReviewEvidence` | merge without lost references |
| `/reasons` | `ReasonList`, `PolicyVersion`, `ReasonForm`, `ReasonUsageView` | references remain immutable historical |
| `/sellers` | `SellerReviewQueue`, `SellerCasePage`, `SuspendWizard`, `RiskEvidence`, `SellerHistory` | suspend requires permission+reason and does not mutate orders blindly |
| `/reports` | `ReportsQueue`, `EvidenceViewer`, `PrivacyGuard`, `DecisionForm` | complainant privacy, evidence access checks |
| `/appeals` | `AppealDetail`, `IndependentReviewerBadge`, `OriginalDecision`, `NewOutcome` | actor separation, no rewrite of original decision |
| `/bulk-operations` | `DryRunSummary`, `ImpactReview`, `ApprovalChain`, `OperationProgress`, `ResultExport` | maker-checker, per-item receipts |
| `/audit` | `AuditSearch`, `AuditDetail`, `DiffViewer`, `VerifiedExport`, `AccessLog` | secure filtering/export, integrity validation |
| `/operations/events` | `OutboxPanel`, `DLQPanel`, `ReconciliationStatus`, `ReplayPreview` | no unauthorized/raw replay and visible lag |
| `/admin-users` | `StaffDirectory`, `RoleGrantEditor`, `SessionRevocation`, `MfaState`, `ApprovalPanel` | least privilege; separate approver |
| `/settings` | `QueuePolicy`, `WorkflowSettings`, `NotificationSettings`, `RetentionStatus` | versioned, audited settings change |

## 4. Moderation detail desktop structure

At canonical 1280 CSS px: sidebar ~200–240px according to HTML reference, top shell, 12-col layout. Queue (roughly 25–30% content), product inspection (remaining) with right-side sticky decision section where safe. **HTML/PNG supersede this descriptive approximation.** Header queue summary shows `waiting`, `in review`, `urgent`, `approved today` only if real metric exists. Product card contains title, public preview, seller info, category breadcrumb, SKU table, rich media, attribute quality hints, revision diff, policy checks, audit trail. Controls: claim, heartbeat indication, release, approve, request changes, reject, escalate and hard-block (permission-gated).

## 5. Taxonomy workspace

Tree supports drag-drop only as proposal, never browser-side authoritative reorder. Show breadcrumb and descendant count; create wizard Step A metadata, Step B attribute rules, Step C SEO/media, Step D impact+review, Step E publish. Side-by-side before/after with version and affected count. Prevent invalid parent choices in UI **and** B2B. Archived categories display immutable reference and redirects. Category schema simulator: sample product verifies field requirements before publishing changes.

## 6. UX flows and edge states

- Opening ticket already claimed: show current owner/expiry; disable protected actions; allow refresh or eligible escalated takeover, never silent override.
- Lost network after approve click: keep same idempotency key, use operation lookup; do not issue new approve with new key until original outcome resolved.
- Seller edits revision during review: show old/new diff, mark stale, invalidate decision form/claim; user must reopen latest ticket.
- Requested reason removed while editor open: 409/422, refresh dictionary retaining text.
- Category move affecting published products: server impact preview, destructive warning, typed confirmation and optional second reviewer.
- Published state pending due to outbox: show `Доставка решения выполняется`, retry status from server, no optimistic display of visibility.
- Missing media: neutral placeholder and issue flag; do not render sample merch as real product.
- Fail closed OIDC: inform staff, audit auth failure; no developer bypass in deployed environments.
- Tables 100k rows: no DOM-all pagination, server sorting; keyboard accessible virtualized rows if needed.
- Suspended seller: explicitly separate new listing ban vs fulfilment of open orders.

## 7. Accessibility and responsive

Target WCAG 2.2 AA; keyboard navigation, skip-to-content, complete accessible labels, error association, non-color statuses, focus management for sidepanels/dialogs, touch targets, reduced motion, no horizontal page overflow at 320px. High-density admin tables may have deliberate *inner table* horizontal scroll with visible column controls; not entire-page scrolling. Print/export modes redact restricted data.

## 8. Visual acceptance

1. Run canonical screenshot at original CSS viewport (derive from HTML) and DPR matching normalized reference; fixed fonts, animations disabled, deterministic timezone and fixtures; record `actual`, `expected`, `diff`.
2. Structural exactness: header, sidebar, top KPI, ticket list, detail view, decision panel, density, borders, colors, typography. Global pixel tolerance should be established from stable fonts/images, not arbitrarily raised until tests pass.
3. Real-data Playwright journey after structural fixture run: category create → seller create/submit → claim → review → approve → B2B ack → B2C public visibility; separate error journeys.
4. Review screenshots by human when no authoritative mobile/tablet originals exist; responsive baselines require explicit approval, not auto-generation.
5. Do not update official baselines without human-approved reason, corresponding diff and changelog.


---

# SOURCE: security/SECURITY_AND_COMPLIANCE.md

# Admin security architecture and threat model

## Identity / access

- OIDC Authorization Code with PKCE via confidential Next.js BFF; verify exact issuer+audience+nonce+state+signature+JWT TTL and key rotation. Never trust `X-Moderator-Id` except segregated test-only env. Server-side mapping `(iss,sub) -> UUID staff_id`; OIDC `sub` may be opaque string.
- MFA mandatory for all staff; step-up for roles, hard-block, wide category migrations, bulk unpublish and export of sensitive data. Specific `amr`/`acr` mappings are configured for chosen IdP, not hardcoded universal `'mfa'` assumption. Enforce sign-in policy on server, not only redirect UI.
- Opaque session cookie (`__Host-` + HttpOnly/Secure/Path=/ + SameSite); session-bound CSRF token; idle and absolute expiry, revocation, device/session list and authentication audit. Private responses `Cache-Control: private,no-store`; invalidate caches on logout/role change.
- `PermissionGuard` centralized server policy. ABAC: capability, staff scope, object sensitivity, regional applicability, maker-checker conflict, ticket claim. `403` on function, property and object mismatches. All privileged direct API requests denied without service auth.
- Admin gateway private network / conditional access / restricted public exposure; TLS, HSTS, CSP enforcing, CORS exact allowlist, rate limits, resource limits, no internal APIs reachable by buyer/seller clients.

## Threat scenarios to test

| Attack/failure | Defense | Test |
|---|---|---|
| Staff forges/modifies JWT claims | JWKS signature+issuer+audience+exp/nbf+IdP roles; subject mapping | altered signature, wrong issuer/aud/key/roles rejected |
| Auth bypass in local mode | production fail closed; startup validator refuses bypass env; test settings only | staging/prod with `NEOMARKET_DEV_OPEN_ACCESS=true` refused |
| Claims ticket belonging to another moderator | lease token hash + fencing + permission + row lock | simultaneous claim barrier; stale token rejected |
| Approves old product revision | immutable snapshot hash + B2B revision CAS | seller edit during review, approval returns conflict |
| Repeated decision double-publishes | unique Idempotency-Key + request hash + inbox | retry same payload same operation, different payload 409 |
| Taxonomy owner can approve own high impact move | maker-checker server separation | own approval refused |
| Category cycle / lost catalog links | cycle check + FK/path constraints + impact preflight | move parent under child and referenced archive rejected |
| Employee accesses seller docs not in scope | RBAC/ABAC object authorization, redacted API, signed scoped URL | cross-seller IDOR denied |
| Arbitrary HTML/SVG injection in product descriptions/media | sanitize HTML, media scan, CSP, no dangerous inline scripts | XSS payload inert in preview |
| Admin export reveals PII | export rights, minimization, TTL object, audit of download | low privilege export rejected |
| Slow huge category moves starve DB | jobs/chunking/timeout/quota, async progress | load and cancellation tests |
| Outbox/retry drops approval | worker leases, persisted receipts, reconciliation, alert | process kill before/after commit |
| CSRF on privilege changes | same-site, CSRF double-submit or session-bound token, origin check | cross-origin mutation 403 |
| SSRF through image/metadata URLs | only verified media refs, outbound allowlist | internal URL forbidden |
| Audit altered/deleted | append-only rights + integrity chain/periodic secure export | tamper detection fail release gate |

## Data minimization and logging

Personally identifiable seller/buyer/reporter data accessible only by explicit duty. Mask sensitive fields by default, record read access on sensitive cases. Logs contain request IDs, status, error code, canonical resource UUID, but not bearer tokens, session cookies, evidence document bytes, unrestricted personal addresses or raw payment data. Retention and data subject rights are legal-policy decisions, documented in ADR for actual jurisdiction. Evidence docs scanned and kept encrypted in segregated object storage with signed access and expiry.

## Two-person rules

Policy/role changes and large destructive admin actions require a **proposer** and a distinct **approver**. High privilege cannot self-grant. Changes queue for review with immutable diff, policy_version, TTL and ID-bound approvals. Break-glass emergency procedure uses time-limited activation, MFA, incident ID, follow-up review and tamper-evident audit; no hidden superuser switch.

## Release security gates

Independent role/access matrix (negative tests for all endpoints), OIDC/MFA on real test IdP, SAST/SCA, secret scanning, dependency/containers review, API request fuzzing, CSP check, XSS/CSRF/SSRF/IDOR tests, audit immutability verification, access logs, two-person approval, backup+restore. Critical P0/P1 unresolved → NO-GO.


---

# SOURCE: migrations/MIGRATION_BLUEPRINT.md

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


---

# SOURCE: planning/IMPLEMENTATION_PLAN.md

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


---

# SOURCE: qa/RELEASE_GATES.md

# Strict iteration gates / release acceptance

## Definitions

- `PASS` ONLY when scenario executed with correct environment, assertion and artifact; `BLOCKED` for absent IdP/payment/infra; `NOT_RUN` for unexecuted test; `FAIL` for violation. No blank/null treated as pass.
- A test relying on mock services validates local logic, NOT real B2B→Admin→B2C integration. Maintain separate fixture/unit, integration, staging tiers.
- Every requirement ID has owner, source, path(s), test_id(s), evidence link, status, execution timestamp and revision.

## Gate G0 — Current source and specification

PASS if current repo is clean/understood, API schema diff is captured, actual docs/stitch HTML/PNG identified, business constraints documented (privacy, category taxonomy status, banned-content policy, seller KYC, appeals). P0 findings have owner/action. Existing dirty changes preserved.

## G1 — Identity / security

Real OIDC login/logout/callback/refresh/revocation with MFA and string `sub` mapping; all high-risk roles/ABAC denied by default; step-up; API negative tests; CSRF, CSP enforcing, IDOR controls, no production bypass; admin route not visible unauthenticated; unique test principal with least privilege.

## G2 — Moderation integrity

Snapshot version pinned, lease/fencing/claim_token verified, `Idempotency-Key` replay hash semantics, B2B exact product-revision CAS, transactional audit/outbox, inbox/ack and public projection correctness. Concurrency test at least 2 moderators and mid-review seller edit; lost ack and retry scenarios prove no phantom publication; hard-block requires correct permissions.

## G3 — Taxonomy quality

CRUD, localized names, tree move/cycle refusal, attr rules typed validation/inheritance, archive referenced blocked or migration plan, dry-run impacted products correct, import/export safe, approvals and versioning, B2B authoritative state and B2C public projection convergence. No hard delete of referenced category.

## G4 — Admin functional UI

All required routes have real API data and working controls, search/cursors/form states, audit timeline, category and moderation flows. Reproduce reference Stitch composition on desktop. Mobile/tablet adaptations approved when no original baseline. No mock metrics, demo images, fake controls or forced-success status.

## G5 — Adjacent admin modules

Seller compliance, complaints, appeals, reasons, brands, bulk ops, operations, audit, staff roles fully scoped and tested. If outside agreed initial release, remove or mark unavailable **and change launch scope explicitly**; cannot claim full-feature marketplace admin with these mandatory requirements blocked.

## G6 — Resilience and recovery

PostgreSQL + real service integration, outbox worker crash/restart and duplicate event, ordering and DLQ, delayed ack, event redelivery, search/cache reconciliation, migration rehearsals, backup restore from offsite, audit integrity test, load test with large queue and taxonomy subtree. SLO/alerts and runbook exercise.

## G7 — Full quality

- ESLint/TypeScript strict, Python lint+types where configured, unit tests PASS.
- No unverified API contract changes, no high/critical SCA scan findings without signed acceptance; private test data.
- Playwright route+role+workflow+error+visual+accessibility tests PASS; three **independent** clean runs after latest code change; no skipped/flaky/uncounted mandatory scenario; screenshot expected baselines immutable unless human-approved.
- Release docs include exact commit SHA, environment, screenshots, traces, logs, migration report, risk status, reviewer and deployment instructions.
- No P0/P1 known issues; unresolved P2/P3 documented explicitly with owners/timeframes where launch policy permits.

## Staging and prod topology

GitHub Actions builds/test externally. Staging hosts services behind private/TLS gateway and real PostgreSQL/Redis plus OIDC test IdP; cannot claim staging performance on VPS 1vCPU/1GiB. Real prod launch requires measured sizing, isolated secrets, backup/restore tests, failure drills, qualified manual approval. Live prod mutations are never run by generic UI QA automation.

## Evidence manifest example

```json
{
  "requirement_id": "MOD-APPROVE-001",
  "test_id": "E2E-MOD-APPROVE",
  "status": "PASS",
  "commit_sha": "<real SHA>",
  "environment": "isolated-staging",
  "executed_at": "<real ISO-8601 timestamp>",
  "evidence": ["qa-reports/run-001/report.html", "qa-reports/run-001/trace.zip"],
  "verified_by": "CI"
}
```

Never populate the example with invented success results; use only actual CI output.


---

# SOURCE: qa/TRACEABILITY.md

# Traceability conventions

## Audited source → spec → code → test

- Audit input source snapshot: `neomarket-full-audit-2026-10-16.zip`.
- Existing Admin API: `services/admin/src/api/routers/moderation.py`; authentication `api/deps.py`; existing models/repo/service; Admin Next `frontend/apps/admin/`.
- Existing B2B category: `services/b2b/src/models/category.py`, `api/routers/categories.py`, `services/category_service.py`.
- Current design: `docs/design-system/stitch/admin-panel/reference.png`, `source-official.html`.
- Proposed Admin BFF contract: `contracts/admin-target.openapi.yaml` (63 operations).
- Proposed B2B internal protocol: `contracts/b2b-admin-internal-target.openapi.yaml` (8 operations).
- `audit/RISK_REGISTER.csv`: 28 defect/risk records keyed `ADM-###` with source and required fix. Source_CONFIRMED vs RISK_TO_TEST distinct.
- `qa/ACCEPTANCE_MATRIX.csv`: 146 scenarios `AT-###`, each tagged with requirement prefix. All initialize `NOT_RUN` until CI/QA.
- Progress per iteration: `docs/automation/ADMIN_PROGRESS.md` in implementation repo, with requirement ID, commit, modified files, actual OpenAPI diff, test IDs/CI artifact links and screenshot diffs.

## Review and evidence

For each implemented new API and screen, register at least one positive E2E scenario, one expected failure and negative access test. For core operations use two concurrent clients and one lost network response. Tests MUST execute actual backend with dedicated PostgreSQL; mocks are acceptable only for isolated unit/component tests.

The `qa/check_release.py` script demands evidence from three distinct independent runs for every acceptance ID. It checks manifest shape, not the authenticity of test execution — the pipeline must generate manifests from actual CI test outputs in separate clean job executions, store append-only artifacts, and review the release sign-off.
