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
