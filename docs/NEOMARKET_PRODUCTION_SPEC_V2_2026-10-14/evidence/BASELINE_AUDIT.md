# NeoMarket — независимый production-readiness аудит

**Дата:** 2026-10-14  
**Объект:** предоставленный `neomarket-audit.zip` (376 ZIP-записей, около 1.85 МБ распакованных данных).  
**Вердикт:** **NO-GO для публичного production**.  
**Тип проверки:** глубокий статический аудит исходников, SQLAlchemy-моделей, миграций, Docker Compose, трёх OpenAPI-снимков, CI, тестов и межсервисных сценариев. **Не** является подтверждением успешного запуска, прохождения нагрузочных испытаний либо проникновения в работающую систему.

## 0. Ограничения и проверяемые результаты

- Изучены B2B, B2C, Admin, общие модули, инфраструктура, миграции, CI и локальные контракты.
- `python -m compileall -q services shared` — **PASS** (синтаксис Python). YAML-файлы Compose и трёх `docs/protocols/*/openapi.yaml` синтаксически разбираются.
- В цепочках Alembic: B2B — 17 ревизий, B2C — 22, Admin — 2; у каждого один корень, одна голова, отсутствующих родителей при статической проверке нет. Это **не** доказывает успешный upgrade/downgrade на настоящей БД.
- В исходниках насчитаны **281 тестовая функция**: B2B — 137, B2C — 128, Admin — 16. Значительная часть — тесты на подставных объектах; сам факт существования тестов не доказывает их прохождения.
- Попытка `pytest -q tests/test_inventory_reservations.py tests/test_reservations.py` остановилась при импорте: `ModuleNotFoundError: No module named 'asyncpg'`. В среде аудита Python 3.13, проект требует >=3.12, CI использует 3.12. Docker в текущей среде не установлен, полноценный стек и PostgreSQL не запускались. **Ни один тест нельзя объявлять пройденным по итогам этого аудита.**
- В отдельном безопасном schema-smoke тесте `SKUCreate(price=-100, stock=-20, images=[{"url":"javascript:alert(1)"}])` и `SKUUpdate(price=-999, stock=-100)` **успешно прошли Pydantic-валидацию**. Это непосредственное подтверждение P1-09/P2-22, не доказательство исполнения SQL-записи.
- В отдельном producer-smoke тесте `ModerationClient.build_product_created_event(...)` вернул корневые ключи `event_type`, `idempotency_key`, `occurred_at`, `payload`, тогда как требуемое обработчиком Admin `event["product_id"]` вызвало `KeyError` на том же словаре. Это прямое подтверждение P0-04 на уровне схемы, не HTTP-интеграционный тест.
- Проверка точных совпадений метода+маршрута по локальным `docs/protocols` (имена `{id}` нормализованы): B2B 19/45 (42.2%), B2C 21/40 (52.5%), Admin 4/23 (17.4%). Это измерение совпадений публичного API, **не процент готовности функциональности**. Некоторые эквивалентные функции находятся по другим путям, иные snapshot/canon отличаются.
- Нельзя оценить численно вероятность потери данных, отказов за месяц, фактический RPO/RTO, latency p95/p99 или пропускную способность без нагрузочного, отказного и восстановительного стенда. В документе вместо выдуманных вероятностей приведены причинно-следственные сценарии.

### Шкала

- **P0 / Release blocker:** критическое нарушение доверия, целостности, ключевого потока или неприемлемая угроза данным; публичный запуск запрещён.
- **P1 / High:** серьёзный риск согласованности, эксплуатации или производительности; должен быть устранён до запуска с реальными пользователями.
- **P2 / Medium:** устранить до масштабирования, либо явно принять ограниченный риск с владельцем и датой.
- **P3 / Low:** улучшения качества и удобства эксплуатации.

## 1. Реестр находок с доказательствами

### P0-01 — Подмена роли модератора: нет проверки личности

**Доказательство:** `services/admin/src/api/deps.py:9-24` принимает `X-Moderator-Id`, только проверяет UUID и возвращает `SimpleNamespace`. `services/admin/src/api/routers/moderation.py:20-72` использует эту зависимость на approve/block; `services/admin/src/main.py:72` регистрирует соответствующие маршруты. Модель `admin_user.py` не включена в действующий механизм авторизации.

**Последствие:** любой клиент, имеющий доступ к Admin HTTP и знающий/получивший UUID назначенного модератора, может выступить от его имени. При публикации `8003:8003` риск особенно высок. **Это подтверждённый дефект авторизации; знание UUID — условие конкретной эксплуатации.**

**Исправление:** JWT/OIDC авторизация модераторов, проверка подписей/issuer/audience/expiry, чтение роли и активности из БД, RBAC, audit trail, закрытие Admin от публичной сети до исправления. Нельзя считать произвольный клиентский заголовок личностью.

### P0-02 — Незащищённые legacy-запросы к складу

**Доказательство:** `services/b2b/src/api/routers/reservations.py:91-110` — `POST /reservations`, `DELETE /reservations/{order_id}` без `verify_service_key` и без `get_current_seller`. `services/b2b/src/services/reservation_service.py:37-53` изменяет остаток SKU. Метод `create` не блокирует SKU `FOR UPDATE` и проверяет `sku.stock`, а не доступный `stock - reserved_quantity`.

**Последствие:** создание/удаление резервов без полномочий; конкуренция может нарушить складские инварианты или привести к необоснованному уменьшению физического остатка. **Удалить небезопасные маршруты, а не скрывать из Swagger.** Запретить обратимое тестовое обращение к ним снаружи.

### P0-03 — Опасная инфраструктурная экспозиция данных

**Доказательство:** `docker-compose.yaml:2-17` — PostgreSQL с `POSTGRES_USER=postgres`, `POSTGRES_PASSWORD=postgres`, binding `5434:5432`; `:19-29` — Redis `6379:6379` без явно заданной аутентификации. `:31-93` — порты сервисов 8001/8002/8003 опубликованы на интерфейсах хоста. В реальной доступности портов также участвуют firewall и сетевые правила, которые в архиве отсутствуют.

**Последствие:** если сервер извне допускает подключения к этим портам, злоумышленник может получить доступ к БД и операциям сервиса. Redis в текущих бизнес-путях не используется (не обнаружены вызовы `get_redis`), поэтому **нельзя** приписывать ему потерю бизнес-данных, но открытый незащищённый Redis всё равно недопустим.

**Исправление:** не публиковать БД/Redis; ограничить Admin/B2B сервисные пути приватной сетью, отдельно вынести gateway с TLS; персональные DB-учётки с минимальными правами, secrets manager, заменить все dev-секреты.

### P0-04 — Несовместимость B2B → Admin event payload: штатная публикация вызывает KeyError

**Доказательство:** `services/b2b/src/clients/moderation.py:66-78,80-98` создаёт `PRODUCT_CREATED` / `PRODUCT_EDITED` c полями `event_type`, `idempotency_key`, `occurred_at`, `payload:{product_id,...}`. Клиент отправляет JSON без преобразования (`:38-44`). `services/admin/src/api/routers/moderation.py:86-95` передаёт его в `services/admin/src/services/moderation_service.py:119-120`, где выполняется `event["product_id"]` **на верхнем уровне**. В штатном payload ключа нет.

**Последствие:** штатное событие не принимается, сервис выдаёт внутреннюю ошибку; добавление SKU или редактирование могут ломаться. Тесты Admin (`services/admin/tests/test_moderation.py:397-423,461-482`) используют другой, плоский формат, поэтому не проверяют реальную интеграцию.

**Исправление:** единый типизированный контракт `event_type/idempotency_key/occurred_at/payload`, валидация Pydantic, integration/contract tests на фактические сообщения обоих сервисов, versioning. Нельзя исправлять только тесты, не исправляя код.

### P0-05 — Модерация не умеет заводить карточки из событий; очередь практически не собрана

**Доказательство:** `services/admin/src/services/moderation_service.py:119-137`: при неизвестном `product_id` возвращается `IGNORED` даже для `PRODUCT_CREATED`; создание `ModerationCard` отсутствует во всём `services/admin/src`, методы для claim/queue/release отсутствуют в `services/admin/src/api/routers`; существуют пустые `auth.py`, `products.py`, `sellers.py`. `docs/protocols/moderation/openapi.yaml` предусматривает queue и управление модераторами.

**Последствие:** реальный товар не попадает в очередь на модерацию по нормальному процессу. **Это неполный ключевой пользовательский поток**, даже если устранить несовпадение JSON из P0-04.

**Исправление:** upsert карточки+SKU из CREATE/EDIT с инвариантами статусов и идемпотентностью, методы списка/claim/release, блокировки конкурирующих модераторов, сценарии end-to-end от продавца до публикации в B2C.

### P0-06 — Нет подтверждённого восстановления БД/аварийного восстановления

**Доказательство:** в переданном артефакте нет скриптов и конфигураций PITR, WAL-архивации, расписаний snapshot/backup, удаления устаревших копий, шифрования, off-site-репликации, инструкций по восстановлению и теста restore. `docker-compose.yaml:95-97` содержит только именованные тома. Тома **не равны резервным копиям**.

**Последствие:** при удалении тома, повреждении диска/БД, неудачной миграции либо потере VPS данные могут быть потеряны необратимо. Это **отсутствие защиты в артефакте**, а не утверждение, что у оператора заведомо нет внешней инфраструктуры backup.

**Исправление:** управляемый PostgreSQL с PITR либо pgBackRest/Barman, off-site encrypted backup, проверяемый restore, регламент RPO/RTO и учения. Отдельно бэкапить все три базы; проверять согласованность B2B/B2C/Admin после восстановления на разные точки времени.

### P1-07 — Отправка межсервисных событий до commit локальной БД

**Доказательство:** `services/b2b/src/services/sku_service.py:83-102,123-146,182-196` вызывает `ModerationClient`/`B2CClient` до commit, который выполняется в роутерах. `services/b2b/src/services/product_service.py:553-561,604-614` аналогичен. `services/admin/src/services/moderation_service.py:21-44,95-117` вызывает B2B перед `db.commit()` в роутере.

**Сценарий:** другой сервис сохранил событие, после этого местный commit не прошёл либо процесс умер. Состояния разных БД расходятся. Для части удалений ловится только `httpx.HTTPError`, сообщение отбрасывается без outbox и без гарантии повтора. **Outbox в B2B применяется к некоторым событиям резерва/блокировки, но не ко всем продуктовым событиям.**

**Исправление:** transactional outbox в каждом производящем сервисе, inbox/processed-event у потребителей, непротиворечивые версии сущностей, DLQ/reconciliation, удаление прямых HTTP side effects из незакоммиченных транзакций.

### P1-08 — Опасная гонка позднего reserve с уже успешным unreserve

**Доказательство:** `services/b2b/src/services/reservation_service.py:368-381`: при отсутствии записей резерва `unreserve` возвращает успех и сохраняет идемпотентный результат. `:55-180`: `reserve` **не проверяет**, что order уже компенсирован/закрыт через `unreserve_operation_repo`. `services/b2c/src/services/order_service.py:136-155,767-855` сохраняет и компенсирует неопределённые результаты вызова reserve; `B2CClient` имеет таймаут 10 секунд (`services/b2c/src/clients/b2b_client.py:11`). Worker начинает компенсировать после grace 60 секунд (`order_service.py:30-33,714-715`).

**Возможная последовательность:** (1) B2B принимает `reserve` и длительно ждёт lock/БД; (2) B2C считает вызов неопределённым, worker инициирует `unreserve`; (3) B2B ещё не создал строки резерва, `unreserve` фиксирует `UNRESERVED`; (4) исходный `reserve` завершается позже и создаёт активный резерв; (5) повтор `unreserve` возвращает ранее сохранённый успех без освобождения нового резерва. Получается «осиротевший» резерв. Для практической реализации сценария нужна задержка исходного запроса дольше grace — **гонка выведена из кода, не воспроизведена на живом PostgreSQL**.

**Исправление:** синхронизировать lifecycle по `order_id` на стороне B2B (одинаковая блокировка/row state для `reserve`, `unreserve`, `fulfill`); tombstone `CANCELLED` должен блокировать любой *будущий* резерв того же `order_id`; проверить race fuzz и fault-injection при ответе/коммите в произвольной последовательности. Это важнее простой ретрай-петли.

### P1-09 — Инварианты остатков не защищены при UPDATE SKU

**Доказательство:** `services/b2b/src/schemas/sku.py:24-44`: `stock`, `price`, `cost_price` без `ge=0`; `services/b2b/src/services/sku_service.py:104-139` присваивает `sku.stock = data.stock` без валидации против `reserved_quantity` и без `FOR UPDATE` SKU; `services/b2b/src/models/sku.py:26-28` не содержит `CheckConstraint`; при резервировании доступность вычисляется `max(stock-reserved, 0)` (`reservation_service.py:500-501`), маскируя невалидное состояние.

**Последствие:** продавец может установить отрицательный stock/price или stock ниже уже зарезервированного; конкурентное изменение остатков не согласовано с новой бронью. Возникают противоречия между физическими остатками, резервами и продажами.

**Исправление:** Pydantic `ge=0` на все входы; SQL CHECK `(stock>=0 AND reserved_quantity>=0 AND stock>=reserved_quantity AND price>=0)` с миграцией после исправления существующих данных; обновление SKU под блокировкой; отдельная политика уменьшения физического остатка при существующих резервах.

### P1-10 — Идемпотентность reserve истекает при живых резервах

**Доказательство:** `services/b2b/src/models/reservation_operation.py:24-28` TTL 3600 секунд; `services/b2b/src/services/reservation_service.py:55-66,88-97` удаляет expired operation и допускает повторное выполнение с тем же ключом. Данные самого резерва по `order_id` не проверяются как одноразовая операция; уникальность записи reservation ограничена `(idempotency_key, sku_id)` (`models/reservation.py:12-19`).

**Последствие:** поздний повтор HTTP reserve через час может повторно увеличить `reserved_quantity` даже для того же заказа. В штатном B2C воспроизведение может быть ограничено его собственной идемпотентностью, но внутренний API всё равно опасен.

**Исправление:** не позволять повторный reserve для завершённого/активного `order_id` с другим semantic request, хранить tombstone достаточный жизненный цикл заказа, отделить retention request-cache от складской идемпотентности; regression-test на >3600 секунд.

### P1-11 — Контур завершения заказа (DELIVERED → fulfill) не подключён

**Доказательство:** `services/b2c/src/services/order_service.py:382-428` содержит `mark_delivered` и `retry_pending_fulfillments`, но глобальный поиск вызовов в `services/b2c/src` не обнаружил ни HTTP-роутера перехода в DELIVERED, ни вызова `retry_pending_fulfillments` в lifecycle `services/b2c/src/main.py:18-42`. Сам протокол (`docs/canon/flows/b2c-orders-flows.md:67-76,1071-1073`) предполагает изменение статуса через Django Admin, которого в архиве нет.

**Последствие:** резерв после фактической доставки может не быть преобразован в списание; даже уже помещённые в `pending_fulfillments` задания не выполняются автоматически. Это функциональный пробел полного процесса доставки, не просто отсутствие теста.

**Исправление:** защищённый workflow delivery через API/операторский интерфейс, фиксируемый переход статуса с журналом, durable fulfill job, отдельный worker со статусами/retry/backoff, e2e до B2B и reconciliation.

### P1-12 — Worker скрывает ошибки и не допускает управляемого масштабирования

**Доказательство:** `services/b2b/src/main.py:25-35` ловит все исключения с `pass` без логов; задача создаётся на каждом API lifespan (`:38-43`). `services/b2b/src/repositories/outbox_event_repo.py:42-49` выбирает первые 100 pending без `FOR UPDATE SKIP LOCKED`, lease и `next_retry_at`; `services/b2b/src/services/reservation_service.py:319-331` делает повтор каждую итерацию без backoff и dead-letter. Аналогично B2C worker живёт в процессе API, `services/b2c/src/main.py:18-42`.

**Последствие:** невидимые сбои, бесконечные попытки первых сообщений, дублирующие параллельные исполнители при масштабировании. Отдельные потребители обладают dedup, но это не заменяет leasing и мониторинг.

**Исправление:** выделенный worker в Compose/оркестраторе; lease/claim `SKIP LOCKED`, persistent attempts/error/next_retry_at, exponential backoff+jitter, DLQ, метрики lag/age, алерты, graceful shutdown и ограничения параллелизма.

### P1-13 — Dev-секреты и JWT по умолчанию

**Доказательство:** `services/b2b/src/core/config.py:14-20`, `services/b2c/src/core/config.py:14-19`, `services/admin/src/core/config.py:5-11`; `docker-compose.yaml:40`. B2B и B2C используют `HS256` с известным значением по умолчанию (`services/b2*/src/core/security.py:19-35`). В Compose ключ Admin указан, а у B2B/B2C их собственные значения остаются дефолтными. **Факт проблемы — в возможности старта без валидных production secrets**, а не в доказательстве, что именно такой runtime развернут.

**Последствие:** при использовании известных ключей возможна подделка JWT или сервисных запросов; один service key чрезмерно расширяет blast radius.

**Исправление:** fail-fast при отсутствии надежных секретов; независимые ключи и audience/scope на направления; ротация без остановки; секреты вне Git и Docker Compose; OIDC либо защищённый ключевой контур.

### P1-14 — Нет защиты входа от перебора и расходования ресурсов

**Доказательство:** отсутствуют rate-limit middleware, IP/account throttling, lockout/detection, лимиты HTTP body на reverse proxy. Логин `services/{b2b,b2c}/src/services/auth_service.py:27-39` проверяет пароль, но не ограничивает попытки; `nginx/nginx.conf` пуст.

**Последствие:** brute-force, массовая регистрация, злоупотребление дорогими B2B-запросами, DoS; риск особенно высок с дорогим bcrypt и прямым доступом к uvicorn.

**Исправление:** gateway TLS+rate limit per IP/user/endpoint, captcha/risk control там, где требуется, лимиты payload/request concurrency и connection pools, security events, audit alert.

### P1-15 — Каталог загружает и фильтрует всё в памяти

**Доказательство:** `services/b2b/src/services/product_service.py:107-143,145-203` — `list_public_catalog()` без пагинации перед фильтрацией; затем Python filters, sorting, slicing, random sample для похожих. Масштаб применения `list_public_catalog` зависит от `ProductRepository`.

**Последствие:** O(число SKU/товаров) CPU/память на запрос, рост p95/p99, heap pressure, потенциальный OOM и блокирование API под высокой нагрузкой.

**Исправление:** WHERE/JOIN/ORDER BY/LIMIT/OFFSET или keyset в PostgreSQL, индексы/FTS, EXPLAIN ANALYZE, разумное ограничение количества SKU и batch IDs; кэш для read-heavy частей после измерений.

### P1-16 — API-contract drift и незаконченные функции

**Доказательство:** статическое сравнение трех локальных `docs/protocols/*/openapi.yaml` против реально объявленных `@router` показывает совпадение 19/45 B2B, 21/40 B2C, 4/23 Admin. Примеры: отсутствуют Admin login/queue/claim/moderators; в B2B нет нескольких маршрутов invoices/accept и auth refresh/logout; B2C нет buyers payment-method CRUD и нескольких протокольных путей. Некоторые функции существуют под другими URL, значит оценивать нужно каждый маршрут и тело отдельно.

**Последствие:** ложное ощущение завершённости, ошибки клиентов и провал контрактного/arbiter-проверяющего слоя.

**Исправление:** зафиксировать ЕДИНСТВЕННЫЙ authoritative OpenAPI + canon revision; build gate на `method/path/security/request/response/status/error`; обосновать aliases/compat; запрет merge при расхождении.

### P1-17 — Production Compose фактически является dev-конфигурацией

**Доказательство:** `Makefile:28-29` цель `prod` — обычное `docker compose up -d --build` с dev compose; `docker-compose.yaml` не устанавливает рестарт-политики, лимиты CPU/RAM, no-new-privileges/read_only, TLS gateway, обязательные секреты, memory/pids limits, DB pool/timeouts. `services/*/Dockerfile` работают от root, скачивают `ghcr.io/astral-sh/uv:latest`, запускают Alembic в CMD каждого приложения (`.../Dockerfile:26-27` и Admin `:21`). `nginx/nginx.conf` пуст.

**Последствие:** перезапуск ноды оставляет неопределённое состояние, небезопасный доступ, непредсказуемые обновления, конфликты миграций при репликах.

**Исправление:** отдельный production-deploy, immutable digest images и nonroot, secrets, gateway/firewall, resources/health/restart, отдельный one-shot migration job после backup, zero-downtime migrations и rollback plan.

### P1-18 — Наблюдаемость и readiness отсутствуют как система

**Доказательство:** `/health` у всех трёх приложений выдаёт только `{status:"ok"}` (`services/*/src/api/routers/health.py`, Admin `src/main.py:11-13`), без DB readiness; B2B worker проглатывает исключения. Отсутствуют метрики Prometheus, OTEL tracing, алерты, structured JSON logs, централизованный correlation ID, error budget и runbooks.

**Последствие:** сервис может отвечать `200 /health`, в то время как транзакции/события не работают; потеря видимости задолженности по reconciliation и задержек в очередях.

**Исправление:** разделить `/live` и `/ready`, проверять DB и необходимые зависимости в readiness; metrics p95/5xx, DB pool/waits, outbox old-age, CANCEL_PENDING, compensation lag, отрицательные стоки, оповещения и trace IDs между сервисами.

### P1-19 — Внутренние схемы БД не гарантируют допустимость данных

**Доказательство:** `services/b2b/src/models/sku.py:26-28` и `models/reservation.py:29-30` не имеют DB CHECK; схема SKU допускает отрицательные цены/stock; `services/b2b/src/services/reservation_service.py:471-475` использует `max(...,0)` при выполнении заказа, поэтому способен скрыть ошибку вместо немедленного остановления операции.

**Последствие:** silent data corruption, инварианты не восстанавливаются после concurrency и ручных операций.

**Исправление:** CHECK/NOT NULL/FK/UNIQUE, запрет молчаливого clamp при списании, транзакционные операции над inventory ledger, ежедневный reconciliation + проверка аномалий.

### P2-20 — Нет полноценных security gates в CI/CD

**Доказательство:** `.github/workflows/*.yml` запускают выборочные сценарии pytest, но нет обязательных SAST, dependency-audit, secret-scan, container-scan, SBOM, покрытия всего тестового каталога и проверок схемы OpenAPI/миграций в составе каждого PR.

**Исправление:** `ruff check`, typecheck, тесты всех сервисов, contract/integration tests, Semgrep/Bandit, pip-audit/OSV, Trivy/Grype, Gitleaks, SBOM, pinned actions, migration smoke and restore drills. Разделить блокирующие и информационные отчёты.

### P2-21 — Отсутствует защищённый audit trail действий модераторов

**Доказательство:** `services/admin/src/models/audit_log.py` пустой, нет записи actor/target/before/after/decision/reason/request_id при approve/block. Привязка `moderator_id` к карточке — не исторический журнал.

**Последствие:** невозможно надёжно расследовать ошибочное/несанкционированное решение или доказать цепочку действий.

**Исправление:** append-only журнал в одной транзакции с решением, права доступа, retention, экспорт и контроль неприкосновенности.

### P2-22 — Ссылки на изображения почти не валидируются

**Доказательство:** `services/b2b/src/schemas/product.py:12-15`, `.../schemas/sku.py:8-11` — `url: str` без protocol allowlist, длины и доменов. В предоставленном коде серверной загрузки по этим URL не обнаружено, поэтому **SSRF не подтверждён**, но рендеринг небезопасных URL клиентом/обработка будущим image service остаются риском.

**Исправление:** `https://`, CDN/object-store allowlist, ограничения длины, MIME/content-type и размера, безопасные загрузки через presigned URL, антивирусное/форматное сканирование в upload-service.

### P2-23 — Неполный lifecycle аутентификации и персональных данных

**Доказательство:** отсутствуют контрактные `/refresh`, `/logout`, управление отзывом сессий, полноценный reset password и внутренние account deletion flows в API. `GET optional user` (`services/b2c/src/api/deps.py:60-73`) не проверяет `is_active` после `get_by_id` (в отличие от `get_current_user`). GDPR/применимые законы зависят от регионов обработки и реального бизнеса.

**Исправление:** refresh rotation, session revocation, отключение аккаунта в обоих режимах зависимости, управление PII/retention и экспорт/удаление при юридической необходимости, минимизация сохранённых адресов и телефонов.

### P2-24 — Неуправляемое накопление данных и операционный долг

**Доказательство:** outbox/processed_events/order histories сохраняются без показанной политики retention/partitioning; для outbox запрос по `status != SENT` и `created_at` без показанного составного индекса (`outbox_event_repo.py:42-49`); guest carts также без видимой очистки по TTL. Важно не удалять idem records до истечения *бизнесового*, а не часового срока.

**Исправление:** retention по типам данных, архивирование, индексы под запросы, `VACUUM`/partitioning после EXPLAIN, scheduled cleanup с юридическими ограничениями, контроль размера БД.

### P2-25 — Неодинаковые error envelopes и риск утечки подробностей

**Доказательство:** Admin отвечает 422 на validation (`services/admin/src/main.py:37-49`), B2B и B2C — 400 (`services/b2b/src/main.py:53-81`, `services/b2c/src/main.py:52-73`). Клиент `B2CClient._get` формирует `detail=str(httpx.HTTPStatusError)` (`services/b2c/src/clients/b2b_client.py:19-33`). Для некоторых ошибок передаются сериализованные details клиента/входных значений.

**Исправление:** единый error contract, публичные safe messages, внутренние details только в защищённых логах, исключения API edge, корреляция request_id.

### P2-26 — Supply chain и runtime hardening

**Доказательство:** базовые образы `python:3.12-slim`, `postgres:16-alpine`, `redis:7-alpine` и `uv:latest` не зафиксированы по digest; контейнеры запускают процессы от root; network-level egress и Linux capabilities не ограничены. Наличие `uv.lock` полезно, но не защищает все layers.

**Исправление:** image digest pinning, SBOM + CVE gate, nonroot user, read-only filesystems при совместимости, immutable build, signature provenance, resource limits, network policies, patched dependencies, проверенный rollback.

## 2. Самые опасные последовательности отказа

| Сценарий | Что может произойти | Доказательство/статус | Необходимая защита |
|---|---|---|---|
| Публикация Admin наружу | Чужое решение о товаре | Дефект P0-01 подтверждён | Настоящая authn/authz и private exposure |
| `POST /reservations` конкурентно с reserve | Склад расходится с резервами | P0-02: отсутствие lock и использования active stock | Удалить legacy endpoint + единственный inventory API |
| Создание SKU → Moderation | Ошибка 500 из-за формы JSON | P0-04 подтверждено статически | Контрактные тесты реального producer/consumer |
| CREATE приходит после исправления JSON | Не появляется карточка модерации | P0-05 подтверждено | Upsert + очередь |
| Remote commit успешен, local DB rollback | Карточка и БД продукта не согласованы | P1-07: архитектурная гонка | Outbox/inbox + reconciliation |
| `unreserve` завершён раньше `reserve` | В B2B может остаться бронь без заказа | P1-08: воспроизводимый по логике race, не прогнан на стенде | lifecycle/tombstones/locks |
| Retry reserve спустя 1 час | Повторное увеличение резервов | P1-10: условия подтверждены | durable idem на весь lifecycle |
| SKU stock уменьшен ниже reservations | Нарушение inventory invariant | P1-09 подтверждено | DB CHECK + locking |
| B2B умер, API ожил | Worker может постоянно падать незаметно | P1-12 подтверждено | логирование/алерты/отдельный worker |
| B2C и B2B восстанавливаются на разные backup timestamps | Не совпадают заказы и резервы | Архитектурный риск без стенда | cross-service reconciliation |
| Диск/том PostgreSQL потерян | Потеря заказов/профилей/товаров | В артефакте нет доказанных backup/restore | off-site PITR + restore test |

## 3. Data durability, consistency и backup-дизайн

### 3.1 Обязательные инварианты

1. Для каждого SKU: `stock >= 0`, `reserved_quantity >= 0`, `reserved_quantity <= stock`, `price >= 0`.
2. `reserved_quantity` для SKU соответствует сумме активных `reservations.quantity` в БД B2B. Важно явно определить, допускаются ли legacy reservations без идемпотентного ключа — лучше прекратить их создание.
3. Для каждого завершённого B2C заказа существуют либо активная бронь (до fulfillment), либо подтверждённый B2B fulfill (после), но не повторное списание.
4. У каждого `CANCELLED` нет активного резерва, у `CANCEL_PENDING` есть восстанавливаемое требование на release, у `COMPENSATED` нельзя позже снова зарезервировать stock тем же order ID.
5. Каждое событие outbox должно быть либо доставлено и подтверждено, либо ожидать retry/DLQ с диагностикой — запрещено исчезновение без исполнения.
6. Любая карточка товара после `PRODUCT_CREATED` должна либо быть поставлена в очередь, либо дать очевидную retriable ошибку, но не отвечать `IGNORED` как success.

### 3.2 Backup / RPO / RTO

Для production определить вместе с владельцем бизнеса, например, **целевые**, а не достигнутые параметры: PostgreSQL RPO ≤5 минут, RTO ≤60 минут (значения требуют расчёта инфраструктуры и нагрузочного подтверждения). Резервировать B2B/B2C/Admin, шифровать вне VPS, тестировать restore минимум ежемесячно, проводить аварийные учения по удалению тестового volume и rollback неудачных миграций.

Нельзя полагаться на одновременный point-in-time restore трёх независимых БД без протокола согласования: после восстановления потребуется reconcile заказов, inventory и moderation events. Внешние платежи (если их добавят позднее) восстанавливаются отдельно через платёжный источник истины.

### 3.3 Полезные проверки целостности (на **тестовой** БД)

```sql
-- B2B: противоречивые SKU
SELECT id, stock, reserved_quantity, price
FROM skus
WHERE stock < 0 OR reserved_quantity < 0
   OR reserved_quantity > stock OR price < 0;

-- B2B: stored reserved_quantity vs live reservation rows
SELECT s.id, s.reserved_quantity,
       COALESCE(SUM(r.quantity), 0) AS actual_reserved
FROM skus s LEFT JOIN reservations r ON r.sku_id = s.id
GROUP BY s.id, s.reserved_quantity
HAVING s.reserved_quantity <> COALESCE(SUM(r.quantity), 0);

-- B2B: старые pending outbox (>5 мин)
SELECT event_type, COUNT(*) AS pending, MIN(created_at) AS oldest
FROM outbox_events
WHERE status <> 'SENT'
  AND created_at < NOW() - INTERVAL '5 minutes'
GROUP BY event_type;

-- B2C: незавершённые компенсации
SELECT compensation_state, COUNT(*) FROM pending_reservation_compensations
GROUP BY compensation_state;

-- B2C: зависшие отмены
SELECT COUNT(*) FROM orders
WHERE status = 'CANCEL_PENDING'
  AND created_at < NOW() - INTERVAL '10 minutes';
```

Эти SQL не требуют изменять данные; запускать с правами SELECT. Порог времени в примерах только для alert-design, не договорный SLA.

## 4. Security threat model

**Активы:** учётные данные и JWT покупателей/продавцов/модераторов, персональные данные и адреса, цены, складские остатки, заказы, данные модерации, межсервисные секреты, PostgreSQL.

**Границы доверия:** браузер/мобильный клиент → публичный gateway → B2C; кабинет продавца → B2B; оператор → Admin; межсервисные B2B↔B2C↔Admin; каждое приложение ↔ своя БД; внешние storage/payment providers (не представлены). Сейчас есть прямые публикации портов и недостаточные различия ролей service key.

**Основные угрозы:** spoofing Moderator header; unauthenticated inventory endpoints; JWT forgery при оставленных dev secrets; brute force login; массовое создание guest carts; compromised B2B key → чужие внутренние действия; подмена ответов из-за отсутствия TLS за пределами внутренней сети; DoS каталогом; error leakage; replay and race inventory events.

**Технические меры:** authn + RBAC, separate service identities, TLS, role-scoped tokens, deny-by-default, rate limiting, structured audit log, secrets manager, network segmentation, automated secret scanning, CI security baseline, least privilege users/DB grants.

## 5. Тестирование: обязательная матрица с критериями

| Тест | Цель / ожидаемый результат |
|---|---|
| Auth negative tests | Ни один protected endpoint не выполняет запись без валидной роли; поддельный X-Moderator-Id отвергается |
| JWT tampering | Изменённый payload, подпись, истекший token, token другой аудитории отклоняются |
| SKU stock concurrency | При 100+ одновременных покупках/изменениях не возникает отрицательных инвариантов |
| Reserve + unreserve with delayed response | При всех перестановках commit/timeout/cancel поздний reserve не оживляет отменённый заказ |
| Retry reserve after TTL | Повтор запроса >3600 сек не резервирует повторно |
| Checkout failpoints | Падение процесса до/после intent commit, B2B reserve commit, B2C order commit, response serialization |
| Cancel failpoints | Падение до/после B2B unreserve и локального status commit не оставляет необратимую рассинхронизацию |
| Fulfill failpoints | 1 доставленный заказ ↔ 1 реальное списание; повтор безопасен; retry подключён |
| Product moderation E2E | B2B create SKU → Admin new card → claim → approve → B2B visible → B2C catalog |
| Product edit/delete E2E | Ошибка сети/commit не теряет событие, видимость товара корректна после retry/reconcile |
| Multi-worker outbox | 2–5 воркеров не приводят к повторным эффектам/голоданию задач |
| DB failover | Потеря соединения/рестарт DB, lock wait, deadlock; HTTP 503 + retry, без ложных 200 |
| Restore/PITR | Бэкап восстанавливается, миграции сходятся, инварианты и связи трёх сервисов проверены |
| Load / soak 24h+ | Установленные SLO p95/p99/error rate, нет OOM, pool exhaustion и растущих очередей |
| Contract tests | Все опубликованные method/path/body/status/security действительно совпадают с authoritative OpenAPI |
| Vulnerability/dependency scan | Нет неприемлемых CVE/secrets/misconfig; решение зафиксировано в CI |

## 6. План исправлений с приоритетами и зависимостями

### Этап A. Изоляция и блокирующие меры безопасности (сначала)

1. Снять публикацию Postgres/Redis/Admin/B2B internal write API; ограничить доступ через firewall и внутреннюю сеть. `Makefile prod` запретить использовать как реальное production deployment.
2. Заменить hardcoded credentials/secrets и добавить fail-fast на неправильные environment variables; внедрить отдельные service identities и JWT identity для операторов.
3. Удалить или обезвредить `POST /reservations`, `DELETE /reservations/{order_id}`. Добавить автоматический regression-test unauthorized access.
4. Внедрить off-site backup и испытать восстановление **до** первой реальной миграции.

**Gate A:** P0-01,02,03,06 закрыты; negative auth tests проходят; restore test pass; нет публичного доступа к БД.

### Этап B. Целостность и сквозная модерация

5. Исправить schema B2B→Admin, добавить обработку CREATED/EDITED/DELETED, очередь, claim и версионирование событий. Прогнать full end-to-end.
6. Вынести все межсервисные сообщения в transactional outbox/inbox; добавить idempotent replay, retry, reconciliation, dead-letter.
7. Ввести безопасную order lifecycle state machine в B2B для позднего reserve/unreserve, персистентный order tombstone и предотвращение replay after TTL.
8. Блокировки при изменении SKU, CHECK constraints и account-level reconciliation; написать миграции с предварительным аудитом существующих данных.
9. Подключить fulfilment runner и реальный защищённый статусный workflow.

**Gate B:** на staging нет неразрешённых несоответствий inventory; все fault-injection тесты проходят; E2E товара и заказа проходит.

### Этап C. Операционная зрелость

10. Отдельные worker deployment и migration job, `/live`/`/ready`, логи/метрики/алерты, устойчивый retry with jitter, replay API и DLQ.
11. Production gateway TLS, rate limiting, request size limits; настройки pool/timeout/statement_timeout/lock_timeout; минимальные DB роли.
12. Перенести каталог в indexed SQL, измерить нагрузку, убрать O(N) операции; профилировать память при больших SKU.
13. Официальный контрактный gate, полное CI с тестами+сканированием, nonroot images, digest pinning, SBOM, rollback/release playbook.
14. Нормативные требования: PII retention, удаление/экспорт данных, audit trail, юридические документы и процессы поддержки по регионам запуска.

**Gate C:** достигнутые на тестах SLO, восстановление из backup, предупреждения доставляются, планы инцидентов проверены.

## 7. Конкретный smoke-test план для разработчика

Использовать отдельный staging, **не production БД**, и полноценно собрать зависимости Python 3.12 из `uv.lock`.

```bash
# из корня проекта
uv sync --frozen --all-packages --dev
uv run ruff check .

# тесты всех сервисов, не только выборочных -k
(cd services/b2b && uv run pytest -q tests/)
(cd services/b2c && uv run pytest -q tests/)
(cd services/admin && uv run pytest -q tests/)

# на отдельной staging PostgreSQL — проверка миграций
(cd services/b2b && uv run alembic current && uv run alembic upgrade head)
(cd services/b2c && uv run alembic current && uv run alembic upgrade head)
(cd services/admin && uv run alembic current && uv run alembic upgrade head)
```

Сначала настроить по сервису `DATABASE_URL` на соответствующие staging DB; `pytest` частично использует in-memory doubles и отдельные PostgreSQL integration тесты, поэтому запуск только pytest без интеграционной конфигурации недостаточен. Скрипты миграции выше должны работать с явно выбранной staging БД и не выполняться одновременно из нескольких реплик. **Не запускать `docker compose down -v` на окружении с данными.**

### Выпускной checklist (все обязательные)

- [ ] Авторизация для B2B, B2C, Admin и межсервисных путей закрывает negative cases.
- [ ] Прямой доступ к DB/Redis из интернета закрыт, все секреты заменены и не имеют dev default.
- [ ] Исправлены CREATE/EDIT/DELETE events, Admin сохраняет карточку и очередь.
- [ ] Все сайд-эффекты привязаны к транзакционным outbox/inbox, есть monitoring/replay.
- [ ] Reserve/unreserve/fulfill выдерживают задержанные ответы, restart и повтор спустя TTL.
- [ ] Складские инварианты обеспечены БД и подтверждены concurrent/stress тестами.
- [ ] Подключены автоматические fulfilment retries и защищённые status changes.
- [ ] Миграции применяются единожды с backup и rollback plan.
- [ ] PITR/backup работает; restore протестирован; RPO/RTO реально измерены.
- [ ] Метрики, alert, incident runbook, ownership и on-call работают.
- [ ] API соответствует выбранному authoritative OpenAPI; тесты всех сервисов проходят.
- [ ] Нагрузочные испытания и soak тест дают подтверждённые SLO, а не предположения.
- [ ] Правила PII, auditing, retention и пользовательских данных согласованы с применимой юрисдикцией.

## 8. Итоговые оценки (экспертный риск, **не тестовая метрика**)

| Область | Состояние | Запуск |
|---|---|---|
| Базовая архитектура, разбиение на сервисы | Есть рабочие основы | Частично |
| Auth/Authz | Критические пробелы в Admin и legacy inventory | NO-GO |
| Согласованность и транзакционность checkout | Продвинутые компенсации, но late reserve race | NO-GO |
| Складские инварианты | Неполные блокировки и DB constraints | NO-GO |
| Событийная интеграция/модерация | Реальный CREATE event несовместим, очереди нет | NO-GO |
| Data durability / backup | Нет доказанного backup/restore | NO-GO |
| High availability / workers | In-process, частичная потеря видимости ошибок | NO-GO |
| Продуктовый API vs протокол | Значительная неполнота/дрейф маршрутов | NO-GO |
| Автоматические тесты | 281 test functions, есть PostgreSQL cases; не выполнены в среде аудита | Не подтверждено |
| Deployment / operations / monitoring | Dev Compose без production hardening | NO-GO |

**Главное решение:** не переносить систему в production по принципу «допишем мониторинг потом». Сначала устранить публичные угрозы, восстановить целостность сквозных flows и подтвердить аварийное восстановление. Текущая реализация является хорошей основой для отдельного production-hardening цикла, **но не готовым production-сервисом**.
