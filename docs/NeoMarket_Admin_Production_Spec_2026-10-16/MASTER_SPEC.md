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
