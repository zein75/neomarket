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
