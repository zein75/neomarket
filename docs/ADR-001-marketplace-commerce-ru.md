# ADR-001 — Российский маркетплейс NeoMarket: продажи, доставка, возвраты, платежи и финансы

**Дата:** 2026-10-20  
**Статус:** `PROPOSED / LEGAL_AND_PSP_REVIEW_REQUIRED`  
**Владелец:** Product Owner NeoMarket  
**Утверждающие:** Product Owner, ответственный за финансы/бухгалтерию, юрист по российскому e-commerce и персональным данным, технический руководитель, менеджер выбранного PSP.  
**Базовый проект:** B2C / B2B / Admin, Next.js Seller, PostgreSQL, Redis, transactional outbox.  
**Источник существующих требований:** `NeoMarket_Seller_Production_Blueprint_2026-10-16/planning/REQUIREMENT_MATRIX.csv`.  
**Важно:** это целевые решения, а не подтверждение текущей реализации и не юридическое заключение. До утверждения не использовать для финансовых операций с реальными пользователями.

## 1. Исходные решения и область применения

| Вопрос | Предлагаемое решение | Статус |
|---|---|---|
| Рынок | РФ, внутренние расчёты в рублях | SELECTED |
| Продавцы | Организации и ИП с проверкой ЕГРЮЛ/ЕГРИП, договора и реквизитов | SELECTED |
| Покупатели | Для первой версии B2C: физические лица-потребители; B2B-юрлица как отдельный будущий поток | PROPOSED; подтвердить |
| Сторона продажи | Каждый seller продаёт свои товары непосредственно покупателю, платформа — оператор/посредник по утверждённому договору | PROPOSED, legal gate |
| Merchant of record (термин PSP) | Не отождествлять автоматически с договорным «продавцом». Определить для каждого вида транзакции в договоре PSP | BLOCKED юридически/PSP |
| PSP | Российский marketplace/split-payments provider; первый кандидат для PoC — ЮKassa Split Payments | PROPOSED, провайдер не подключён |
| Распределение денег | PSP распределяет продавцам/платформе по собственной разрешённой схеме, без самовольного хранения клиентских средств NeoMarket | PROPOSED |
| Доставка | Seller-fulfilled: продавец выбирает/нанимает перевозчика и отвечает за исполнение в пределах закона и договора | SELECTED |
| Валюта | RUB; цены, комиссии, итоговые суммы в целых копейках (`bigint`) | SELECTED |
| Мультипродавцовость | `buyer_order` и по одному или более `seller_order` на продавца | SELECTED |
| Комиссия | Версионируемая формула из договора, без изменения истории | PROPOSED; ставки договорные |
| Возврат/ресток | Возврат денег и возврат физического товара — **разные состояния** | SELECTED |
| Финансовый учёт | Двойная запись внутри выбранной учётной модели, отдельно от фактического PSP settlement | SELECTED |

### Запреты
- Не превращать технический «wallet» в самостоятельное хранение денег клиентов/продавцов без правовой модели и договора PSP.
- Не считать checkout оплаченным по browser redirect, frontend callback или одному HTTP-ответу без верификации в PSP.
- Не делать `seller_balance += price` при создании заказа.
- Не корректировать прошлые цены, налоги, комиссию или юридическое лицо продавца после оформления: создавать immutable snapshots.
- Не считать delivery/refund подтверждёнными только со слов продавца без предусмотренного процедурой источника доказательства.
- Не выдавать API, перечисленные ниже, за существующие: **TARGET CONTRACTS** с миграцией от нынешних эндпоинтов.

## 2. Архитектурные альтернативы и решение

### A. Платформа — прямой продавец (MoR / reseller)
Плюсы: единый продавец и возможная простота взаимодействия с покупателем. Минусы: платформа берёт на себя основные договорные, налоговые, кассовые и товарные обязательства, требуется закупочная/комиссионная модель. **Отклонено для MVP** до изменения бизнес-стратегии.

### B. Продавцы заключают договор продажи; платформа предоставляет инфраструктуру/сопровождение
Плюсы: совместимо с seller-fulfillment, понятная декомпозиция seller orders. Минусы: отдельные продавцы, агентский/посреднический договор, чеки, обязанности агрегатора, KYB/PSP onboarding и правила претензий. **Выбранная целевая модель при условии юридического согласования**.

### C. Платформа собирает все средства на обычный банковский счёт и затем перечисляет продавцам
**Не утверждается** без правового обоснования, согласования с PSP, бухгалтерией и компетентным специалистом по платёжному регулированию. Предпочесть PSP-схему split/settlement.

### Режимы PSP (решить до GA)
- **MODE-SPLIT-IMMEDIATE (базовый для PoC):** один платёж покупателя, PSP распределяет средства продавцам и комиссию платформе по поддерживаемой схеме. NeoMarket фиксирует подтверждённые транзакции, распределения, комиссии, возвраты и реестры; *не* инициирует вторую выплату уже оплаченных продавцу сумм. FIN-09/10 проверяются как идемпотентность PSP distribution/transfer и исключение двойного settlement; отложенные payout API недоступны без поддержки провайдера.
- **MODE-DELAYED-SETTLEMENT:** только если договор PSP прямо разрешает удержание и выплаты по условиям заказа, payout batches, reserve и возвраты до/после payout. Добавить управление payout instructions, compliance, удержаниями и reconciliation. Нельзя реализовать задержку перечисления обычной внутренней БД без полномочий.

**Нерешённый выбор:** точный коммерческий продукт PSP, договорная сторона инкассации, бенефициар, порядок холда/проведения/сплитования, чья ККТ формирует чек и по каким правилам.

## 3. Регуляторные и договорные вопросы (LEGAL GATES)

**LEG-01 — применимость 289-ФЗ и 290-ФЗ** (действуют с 2026-10-01): тип платформы, критерии реестра, раскрытие правил, идентификация партнёров/товаров, жалобы, порядок изменений условий, защита покупателей, доступ к данным и взаимодействие с госорганами. Юрист фиксирует применимость каждой обязанности и артефакт доказательства. Источники: https://government.ru/news/60052/ ; https://www.consultant.ru/document/cons_doc_LAW_519660/7d3fcc44b4ba51f59adb902ca425f3f6327a0b37/ .

**LEG-02 — договоры**: платформа↔продавец (агентский/иной возмездный договор, комиссия, маркетинговые услуги, споры, штрафы, доставка, escrow/PSP, права на контент); продавец↔покупатель (оферта, сроки, возврат, гарантия); платформа↔покупатель (условия сервиса и посредничества). В checkout показать **конкретного юридического продавца** для каждой позиции и снапшот принятых условий.

**LEG-03 — 54-ФЗ / фискализация / ФФД**: определить роль агента, кому принадлежит ККТ/обязанность выдачи чека, набор предметов расчёта (товар, доставка, комиссия), признаки предоплаты и её зачёта, чек полного/частичного возврата. Для агентской схемы проверить реквизиты поставщика (теги 1224/1226, при необходимости агентский признак 1222) по актуальной версии ФФД. Источник ФНС: https://www.nalog.gov.ru/rn76/news/activities_fts/16466380/ . Не считать платёж завершённым в бизнес-отчёте, если требуется фискализация и её результат не обработан; платежный статус и receipt-status хранить раздельно.

**LEG-04 — НДС**: основная ставка с 2026-01-01 равна 22%, но возможны 10%, 0%, специальные 5/7%, освобождения и другие режимы. Нельзя сделать `VAT=22%` для всех SKU. `tax_policy_version`, `seller_tax_regime_snapshot`, `vat_rate_code`, `vat_amount_kopecks`, `tax_point` отдельно по товару/доставке/комиссии. Смена ставки между оплатой и отгрузкой требует формализованных правил бухгалтера и тестов. Источник: https://www.nalog.gov.ru/rn39/ifns/imns_39_26/info/16596254/ .

**LEG-05 — потребительские возвраты**: для B2C дистанционной продажи ст. 26.1 ЗоЗПП, сроки 7 дней / 3 месяца при отсутствии надлежащей письменной информации, отказ до передачи, срок возврата денег при применимых условиях до 10 дней с требования, возможные исключения и отдельные правила товара ненадлежащего качества. Приём/инспекция возвращённого товара не может автоматически отменять законные сроки выплаты. Источник: https://zpp.rospotrebnadzor.ru/news/federal/572363 ; https://zpp.rospotrebnadzor.ru/news/federal/547002 .

**LEG-06 — платежи и 161-ФЗ**: контракт PSP определяет владельцев расчётных счетов и поток денег; не хранить PAN/CVV, использовать hosted checkout или сертифицированный SDK; согласовать chargeback, отрицательные остатки, clawback и disputed funds.

**LEG-07 — персональные данные и доставка**: роли оператора/обработчика по 152-ФЗ, локализация и территориальные требования, DPA/поручение на обработку между платформой, продавцом и перевозчиком; минимизация адреса/телефона (только seller-specific seller order), сроки хранения, удаление и доступы.

**LEG-08 — виды товаров**: запрещённые/ограниченные категории, обязательная маркировка «Честный знак», сертификаты и лицензии, требования к возврату специализированных товаров. Отдельная валидация category policy; никогда не считать любой товар свободно допустимым.

**LEG-09 — B2B-покупатели**: если добавляется оплата юрлицом по счёту, выделить отдельные customer types, договор/счёт/УПД/ЭДО, отсрочку оплаты, налоги и обработку возвратов. **Не смешивать** с правами B2C потребителей и не активировать без отдельного ADR.

### Документы, без которых нельзя включать коммерческие платежи
Подписанный ADR; утверждённые оферты и договор с продавцом; договор с PSP и схема потоков денег; подтверждённая схема фискализации и чеков; правила комиссий, удержаний, возвратов и chargebacks; договоры/политики передачи ПДн; схема претензий и доставки; KYB-анкета продавца; инструкции бухгалтерской сверки; оценка применимости 289/290-ФЗ.

## 4. Разделение доменов и владельцы данных

| Домен | Источник истины | Ответственность |
|---|---|---|
| Catalog / SKU | B2B | Продукт, продавец, опубликованная ревизия, атрибуты |
| Inventory | B2B | `on_hand`, `reserved`, операции, возврат в продажу |
| Checkout / Master order | B2C/Order | Покупатель, заказ, snapshot стоимости, payer, allocation |
| Seller fulfillment | Fulfillment domain (отдельная подсистема или модуль Order API) | Seller orders, shipment, proof, carrier reconciliation |
| Returns | Returns domain | Требования покупателя, решения, return items, осмотр |
| Payments | Payment adapter/service | PSP payment ids/statuses, verified webhook, refund requests |
| Ledger / Settlement | Finance domain | Финансовые проводки, суммы, комиссии, settlement, сверка |
| Identity / KYB | Identity/Seller | Юрлица, полномочия сотрудников, MFA |
| Admin | Admin | Жалобы, апелляции, аудит, policy decisions |
| Receipts | Fiscal service / PSP provider | Статус фискализации, ID чека, корректировки |

Межсервисная связь: только версионированные события через transactional outbox/inbox и подписанные/аутентифицированные API. **Не создавать сквозные транзакции через несколько БД**: локальные транзакции, durable saga state и compensating transitions, идемпотентность всех шагов.

## 5. Снимки, суммы и инварианты

- Финансовые значения `int64 amount_kopecks` (не JSON float); `currency='RUB'`; ставки `Decimal` со строго утверждённым округлением на уровне строки/налога/комиссии. Несовпадение итогов → `409 AMOUNT_MISMATCH`.
- Снимок `buyer_order`: `buyer_order_id`, `buyer_type`, `placed_at`, `currency`, `items_total`, `shipping_total`, `discount_total`, `tax_total`, `payable_total`, `seller_allocations`, `pricing_rule_version`, `consents_version`.
- `order_item_snapshot`: `seller_id`, `seller_legal_name`, `seller_inn`, `sku_id`, `product_revision`, `title`, `qty`, `unit_price`, `discount_alloc`, `vat_rate_code`, `vat_amount`, `sale_terms_version`.
- `seller_order`: `buyer_order_id`, `seller_id`, `seller_order_total`, `item_qty`, `shipping_quote_id`, `ship_by`, `deadline`, `address_scope`; покупательские PII доступны только продавцу своей части и только для исполнения.
- Сумма входящего платежа должна совпадать с `payable_total`; сумма seller allocations + platform-owned fees/shipping/discount adjustments должна сверяться с PSP split plan, без двойного учёта доставки.
- Количество return request по `order_item`: `previously_returned_qty + active_approved_qty + new_requested_qty <= delivered_qty`; при возврате денег отдельная защита от переплаты.
- `restock` только после принятия решения о пригодности единиц; уникальный `(return_inspection_item_id, action_type=RESTOCK)` либо уникальный operation ID исключает двойное начисление склада.
- Все операции должны быть tenant-scoped и содержать `actor`, `reason`, trace/correlation ID; после подтверждения финансовые записи нельзя редактировать/удалять (только сторно).
- Settlement window timezone `Europe/Moscow`, хранение timestamp в UTC, сохранение `window_start`, `window_end`, cut-off policy version и неизменяемых snapshot по времени.

## 6. Жизненный цикл заказа и доставки

### Buyer order
`DRAFT -> VALIDATING -> PAYMENT_PENDING -> CONFIRMED -> PARTIALLY_FULFILLED -> COMPLETED` и боковые `CANCEL_REQUESTED`, `CANCELLED`, `RETURN_IN_PROGRESS`, `PARTIALLY_REFUNDED`, `REFUNDED`, `DISPUTED`. Итог master order агрегируется из seller orders и платежных состояний, **не просто копированием последнего child-status**.

### Seller order
`NEW -> ACCEPTED -> PICKING -> PACKED -> SHIPPED -> DELIVERED -> CLOSED`; отдельные отмена до отгрузки, исключения, lost-in-transit и возвраты. Все допустимые переходы реализовать явной таблицей, permission/policy/If-Match, audit и transactional outbox. Отклонение продавцом → policy-based cancellation, освобождение резервов и финансовое возмещение, без потери master order.

### Seller-managed delivery
1. Seller сохраняет валидные зоны доставки, способы (собственный курьер/договорной перевозчик), тарифы, предельные вес/габариты, cut-off и SLA. Не смешивать расчёт тарифа с display mock.
2. При checkout адрес покупателя нормализуется; backend запрашивает и **замораживает** доступное предложение тарифа, срок, expiry и версию договора. Если достоверного тарифа нет, checkout не подтверждает фиктивную доставку.
3. После сборки seller создаёт `shipment intent`; если есть carrier API — документ/трек через adapter, идемпотентно. Для своего курьера — разрешённый manual tracking с событием передачи и подтверждением доставки (без фиктивного carrier status).
4. Изменения статуса carrier: подпись/webhook/provider lookup, дедупликация, out-of-order replay, соответствие реальному shipment. Пользовательское действие продавца не подменяет подтверждение перевозчика.
5. При timeout carrier: `PENDING_PROVIDER_CONFIRMATION`, операция восстанавливается с тем же ключом, worker выясняет состояние, alerts на SLA и неразобранный pending.
6. Чек доставки, распределение транспортных расходов и возврат стоимости услуги определяются по юридическому договору и фискальным правилам.

### Отмена и компенсация
- Checkout создаёт устойчивую операцию `checkout_operation` и резервы; невозможность оплаты после допустимого срока → освобождение резервов через durable worker; **не** пересоздавать покупательский заказ без выяснения outcome.
- Отмена конкурирует со сборкой/отгрузкой только через блокировки/версии и state machine.
- После отгрузки использовать возврат/претензию, а не невалидный silent `CANCELLED`.

## 7. Возвраты: ORD-14—ORD-17

**Принцип:** юридическое требование покупателя (`claim`) и физический возврат (`RMA`) могут двигаться независимо. Физическая экспертиза нужна для restock, но не служит универсальным основанием затягивать законный refund.

| ID | Точное требование из Seller QA | Реализация и проверка |
|---|---|---|
| **ORD-14** | `return partial units` | `return_items` c `quantity`, конкретный seller order + item. Частичный возврат 1 из 3, сохранение остальных, независимый refund allocation, пересчёт order totals. Доказать UI + API + DB. |
| **ORD-15** | `return qty cannot exceed delivered` | В транзакции с блокировкой и учётом уже открытых возвратов запрет `qty > delivered - claimed`; одновременно 2 запроса, один `409 RETURN_QUANTITY_EXCEEDED`. Не путать доставленные/отгруженные. |
| **ORD-16** | `restock accounting once` | Осмотр, disposition `RESTOCK/QUARANTINE/WRITE_OFF`; уникальный warehouse ledger operation ID; duplicate webhook/worker retry/timeout не меняют stock дважды. Проверить `on_hand`,`reserved`, ledger и баланс. |
| **ORD-17** | `provider outage enters recoverable pending and alerts` | Недоступность carrier/PSP создаёт persistent `PENDING_RECONCILIATION`, очередь ретраев с backoff + DLQ, алерт и восстановление по provider ID. Нельзя показать ложный успех. Проверить отказ+возобновление. |

Дополнительно: buyer-facing срок рассмотрения, доказательства факта доставки, фотографии в приватном storage, idempotent refund, причину, историю, спор/appeal, ограничение доступа чужого seller. Пользователь должен видеть реальный статус и канал претензии.

## 8. Платежи, комиссии, ledger и расчёты: FIN-01—FIN-13

### Money flow — две допустимые модели
**MODEL A — immediate PSP split (первый PoC):** клиент платит PSP; провайдер распределяет продавцам и платформе; `psp_distribution` хранит подтверждённые суммы. `payout` в NeoMarket — запись подтверждённой операции PSP, а не повторный перевод денег. Нельзя показывать «доступные к выплате деньги платформы», если их нет на её балансе.

**MODEL B — provider-held delayed settlement:** только при заключённом договоре соответствующего продукта PSP. Сохранять provider funds status, reserve, settlement instruction, payout status, dispute adjustments, external reconciliation. Собственный ledger **не заменяет** контролируемый провайдером баланс.

### Ledger accounts (пример общей схемы)
- `PSP_RECEIVABLE / PSP_CLEARING` — только если учётная модель действительно отражает право требования/расчёт платформы.
- `SELLER_PAYABLE` — только если именно платформа имеет реальное обязательство перечислить продавцу; при immediate split может быть **отсутствующим**, а `seller_settlement_observed` — аналитическим off-platform событием.
- `PLATFORM_COMMISSION_REVENUE` — подтверждённая комиссия, не вся стоимость товара.
- `COMMISSION_REFUND_ADJUSTMENT`, `PSP_FEES_EXPENSE`, `BUYER_REFUND_PAYABLE`, `CHARGEBACK_DISPUTE`, `SETTLEMENT_SUSPENSE` по необходимости юридической модели.

Записи двойной бухгалтерии: `ledger_transaction_id`, `entry_id`, `account_id`, `debit_kopecks`, `credit_kopecks`, `currency`, `source_type/id`, `reversal_of`, `posted_at`, `policy_version`; `sum(debit)=sum(credit)` по каждой транзакции и валюте. **Не приписывать платформе денежные активы и обязательства, которыми фактически распоряжается PSP.** Отдельные reconciled informational subledgers допускаются, но должны обозначаться как учёт provider settlements.

### Комиссия
Версионированный договор `seller_commission_policy`: `base = net/gross` строго выбрать; `rate_bp`, фиксированная плата, min/max и исключения, распределение округления по line item, кто несёт PSP fee, возврат/удержание комиссии при refunds, chargeback, промо и доставки. В заказе хранить snapshot формулы и расчёта. Не пересчитывать комиссию старого заказа по текущему тарифу.

### Таблица приёмки
| ID | Точное требование | Контракт/реализация и обязательное evidence |
|---|---|---|
| **FIN-01** | `snapshot amount matches accepted master order` | В момент оплаты frozen `master_order_total`, split allocations и PSP request совпадают по копейкам, валюте, версии. Подмена frontend total → 409. |
| **FIN-02** | `commission policy` | Версия политики и calculation breakdown; изменение тарифа после оформления не меняет историческую операцию; детерминированные округления. |
| **FIN-03** | `payment not counted as paid until verified PSP webhook` | Signed PSP notification плюс provider-status lookup при сомнении; browser redirect/непроверенный event не меняет `payment=SUCCEEDED`. |
| **FIN-04** | `duplicate PSP webhook no duplicate ledger` | Уникальный provider event ID и effect ID, транзакционный inbox; дубли/ретраи не создают проводок. |
| **FIN-05** | `chargeback reversal` | Отдельный dispute state, hold/reversal по договору, возврат провайдеру и компенсирующая проводка; сохранение trace. |
| **FIN-06** | `partial refund` | Поддержка количества/копеек по seller lines, многократных частичных возвратов в лимите оплаченного, provider receipt + fiscal refund. |
| **FIN-07** | `settlement window cutoff` | Freeze окна в Europe/Moscow с versioned policy, события после cut-off идут в следующее окно, без ручных перезаписей. |
| **FIN-08** | `double entry balanced` | Для каждой проводки сумма debits равна credits (RUB), immutability/reversal, DB transactional assertion и тесты. |
| **FIN-09** | `payout idempotent` | Идемпотентная provider settlement/distribution request; у MODE A не создавать второй payout, у MODE B повтор provider payout id не дублирует перевод. |
| **FIN-10** | `failed payout retained pending and reconciled` | У провайдера timeout/failure → persisted pending, poll/reconcile и alerts; ни ложного успеха, ни потери операции. |
| **FIN-11** | `seller cannot alter bank without MFA` | Новые реквизиты через step-up, maker-checker по риску, аудит old/new masked, delay/notification, KYB owner match; проверка claim freshness. |
| **FIN-12** | `cross tenant payout 404` | Запрещено читать payout/settlement чужого продавца даже зная UUID; deny и audit. |
| **FIN-13** | `concurrent refund+settlement yields correct reconciliation` | Конкурентный refund/settlement на одну денежную сумму: locks/sequence/fencing, одни корректные проводки, reconciliation against PSP. |

**Все FIN остаются GA-blocking, если выплаты входят в релиз:** именно так определено в существующей матрице Seller Hub. MODE A не является основанием удалить FIN-09/10: они проверяют фактический provider split/settlement в согласованной трактовке.

## 9. Целевые модели данных / Alembic

`orders`, `order_items_snapshot`, `seller_orders`, `seller_order_items`, `order_status_history`, `checkout_operations`, `inventory_reservations`, `shipping_quotes`, `shipments`, `shipment_events`, `carrier_provider_operations`, `return_cases`, `return_items`, `return_inspections`, `return_stock_operations`, `payment_intents`, `payment_operations`, `psp_events_inbox`, `payment_splits`, `refund_requests`, `refund_allocations`, `chargeback_cases`, `commission_policies`, `commission_snapshots`, `ledger_accounts`, `ledger_transactions`, `ledger_entries`, `settlement_windows`, `settlement_reconciliations`, `provider_transfers`, `payout_attempts`, `fiscal_receipts`, `outbox_events`, `inbox_events`, `audit_events`.

### Ограничения БД (обязательный минимум)
- UUID PK, immutable unique `client_operation_key` scoped by owner + operation type, `request_fingerprint`; повтор с другим fingerprint → HTTP 409.
- `CHECK (qty > 0)`, `CHECK (amount_kopecks >= 0)` для сумм положительных операций, `CHECK (currency='RUB')` в v1; у debit/credit две неотрицательные колонки, ровно одна положительна.
- UNIQUE `(provider, event_id)` для inbox; UNIQUE `(provider, external_payment_id)` при наличии; UNIQUE `(source_type, source_id, posting_kind)` для финансового effect при защите от дублей.
- UNIQUE `(inspection_item_id, restock_kind)` для складского effect; FK к seller order/items и проверяемые количественные ограничения *в транзакции*, а не только `CHECK`.
- FK `seller_order.buyer_order_id`; composite tenant FK либо серверный enforcement, запрещающие смешивание `seller_id`.
- Optimistic `version`/If-Match для заказов и возвратов; row locks/advisory locks для количества/settlement; atomic outbox alongside state transitions.
- Секреты PSP — из Secret Manager/закрытых env, никогда в БД снимков финансов и audit.
- Платёжные и фискальные документы сохраняются по применимой retention policy; никакой безусловной `ON DELETE CASCADE` на историю платежей.

### Согласованность версий и миграции
Expand → migrate/backfill → dual-read/compatible API → verify → cutover → contract. Миграции проверять на копии staging; rollback базы только по утверждённому restore/forward-fix plan. Использовать существующие таблицы B2C/B2B без параллельного копирования одних и тех же фактов.

## 10. Целевые API-контракты (не выдавать за текущие)

Все mutating endpoints принимают заголовок `Idempotency-Key`; конфликтный body с прежним ключом — `409`; `If-Match` для изменяемых сущностей; ошибки — `application/problem+json`, с `type,title,status,code,request_id`; пагинация курсором, tenant-scoped authorization.

| Endpoint | Кто вызывает | Инвариант |
|---|---|---|
| `POST /api/v1/checkout/operations` | Buyer BFF → B2C | Атомарный `order_intent`, snapshot цен/доставки и резервы; recoverable op ID |
| `GET /api/v1/checkout/operations/{id}` | Buyer | Заказ/платёж после timeout не создаются повторно |
| `GET /api/v1/seller/orders` | Seller BFF → Fulfillment | Только owner-scoped seller orders |
| `GET /api/v1/seller/orders/{id}` | Seller | Данные покупателя минимальны |
| `POST /api/v1/seller/orders/{id}/accept` | Seller | state machine + If-Match |
| `POST /api/v1/seller/orders/{id}/shipments` | Seller | Valid qty, idem carrier operation |
| `POST /api/v1/orders/{id}/returns` | Buyer | Qty delivered constraint + immutable claim |
| `POST /api/v1/returns/{id}/inspect` | Seller | disposition, restock once |
| `GET /api/v1/returns/{id}` | Buyer/Seller scoped | Статусы RMA и refund раздельны |
| `POST /internal/payments/intents` | Order → Payment | Frozen amount+PSP split plan+provider request ID |
| `POST /api/v1/payments/webhooks/{provider}` | PSP | Verify signature and status, inbox dedupe |
| `POST /internal/payments/refunds` | Returns/Finance → PSP adapter | Approved refund, idem+max paid |
| `GET /api/v1/seller/finances/transactions` | Seller finance role | Только свои, provider status и `as_of` |
| `GET /api/v1/seller/finances/settlements` | Seller finance role | Only own verified provider distributions |
| `POST /api/v1/seller/finances/bank-change-intents` | Seller owner | Step-up required; нельзя менять реквизиты напрямую |
| `POST /internal/settlements/reconcile` | Finance worker | Compare to PSP registers, never self-approve silent difference |
| `GET /api/v1/admin/finance/reconciliation` | Admin finance | Aggregates with audit, approval rules |

### Пример create return request
```http
POST /api/v1/orders/bo_123/returns
Idempotency-Key: 12e277d8-7cfb-470c-83be-7c693a6eb0e5
Content-Type: application/json

{
  "seller_order_id": "so_123",
  "items": [{"order_item_id": "oi_123", "quantity": 1, "reason_code": "NOT_AS_DESCRIBED"}],
  "comment": "Товар не соответствует описанию"
}
```
Ответ `201` c `return_case_id`, `status`, `requested_qty`, `refundable_amount_kopecks` (первоначальная оценка, не подтверждение выплаты), `refund_status`, `restock_status`; конфликт `409 RETURN_QUANTITY_EXCEEDED`, недопустимая версия `412`, неизвестная чужая сущность `404`.

### Пример подтверждённого платежа из события (event schema)
```json
{
  "event_id": "evt_123",
  "event_type": "PaymentConfirmed.v1",
  "occurred_at": "2026-10-20T10:15:00Z",
  "correlation_id": "co_123",
  "payment_id": "pay_123",
  "buyer_order_id": "bo_123",
  "provider": "configured_local_psp",
  "provider_payment_id": "psp_123",
  "amount_kopecks": 105000,
  "currency": "RUB",
  "status": "SUCCEEDED",
  "verified_against_provider": true
}
```
Это **внутреннее событие NeoMarket**, выпускаемое **после** верификации PSP webhook/API, а не произвольный внешний webhook. Boolean `verified_against_provider` сам по себе не является механизмом безопасности.

### PSP adapter interface (v1)
```text
create_payment(order_snapshot, split_plan, idempotency_key) -> ProviderPayment
get_payment(provider_payment_id) -> ProviderPayment
verify_webhook(headers, raw_body) -> VerifiedProviderEvent
create_refund(payment_id, item_allocations, amount, idempotency_key) -> ProviderRefund
get_refund(refund_id) -> ProviderRefund
get_settlement_or_distribution(provider_reference) -> ProviderSettlement
list_reconciliation_registers(date) -> ProviderRegister
get_fiscal_receipt(reference) -> FiscalReceiptStatus
```
Утвердить capabilities flag из договора PSP: `supports_single_payment_multi_seller`, `supports_seller_payout_delays`, `supports_partial_split_refund`, `supports_chargeback_recovery`, `supports_merchant_fiscal_receipts`, `supports_holding_and_release`, `supports_sandbox`, `supports_webhook_signature`, `supports_register_export`. Требуемая функция отсутствует → fail closed или другой официально утверждённый сценарий.

### Carrier adapter (seller fulfilled)
```text
quote(seller_id, origin, destination, parcel, tariff) -> SignedQuote
create_shipment(seller_order_id, parcels, quote_id, idempotency_key) -> ShipmentOperation
get_shipment(provider_shipment_id) -> Shipment
verify_carrier_event(headers, raw_body) -> VerifiedCarrierEvent
cancel_shipment(provider_shipment_id, idempotency_key) -> Operation
```
Для своего курьера — `MANUAL_FULFILLMENT` как самостоятельный, явно отображаемый канал с аудитом и подтверждением доставки; не выдавать manual события за provider-signed.

## 11. События и сценарии сбоев

События `OrderPlaced.v1`, `SellerOrderAllocated.v1`, `ReservationConfirmed.v1`, `PaymentConfirmationPending.v1`, `PaymentConfirmed.v1`, `PaymentFailed.v1`, `ShipmentCreated.v1`, `ShipmentDelivered.v1`, `ReturnRequested.v1`, `ReturnApproved.v1`, `ReturnItemInspected.v1`, `RestockApplied.v1`, `RefundRequested.v1`, `RefundSucceeded.v1`, `RefundFailed.v1`, `SettlementObserved.v1`, `PayoutInstructionSubmitted.v1` (только MODE B), `PayoutConfirmed.v1`, `ChargebackOpened.v1`, `ChargebackResolved.v1`, `ReconciliationMismatchDetected.v1`.

Требования: at-least-once delivery, consumer inbox, dedupe по `(aggregate_id,event_id)`, schema version, outbox в транзакции изменения объекта, retry, DLQ, корреляция. Не пытаться гарантировать exactly-once сетевую доставку — гарантировать exactly-once **business effect**.

### Outage drill matrix
1. PSP create timeout после фактического принятия → получить исходную операцию по idempotency/provider reference, не создавать вторую.
2. Два webhook/обратный порядок → одно business effect, проверка статуса у провайдера.
3. Carrier 503 после создания label → pending, poll+recover, отсутствие двух labels.
4. DB outage после внешней операции PSP → durable intent до вызова; recovery из provider register, не потерять оплату.
5. Refund + payout race → lock/serializable strategy и сверка, нет отрицательного незарезервированного результата.
6. Worker crash после commit до publish → outbox доставит event после рестарта.
7. Контроль долгих refund requests и истекающих регуляторных SLA → alert, очередь разбирательства, владельцы эскалации.

## 12. Описание обязательных UI (Seller / Buyer / Admin)

**Seller → Orders:** inbox заказов, статусы, SLA, кнопки только доступных переходов, список SKU/qty, ответственный, сборка, частичные отгрузки, трек, доказательства, возвраты и жалобы; buyer PII только необходимая для передачи заказа.

**Seller → Returns:** запросы по конкретной позиции, допустимые причины, решение с обоснованием и уровнем прав, RMA, логистика, инспекция, disposition, история; refund отображать с подтверждённым PSP status и информацией о сроках.

**Seller → Finance:** начисления/распределения/удержания, комиссии, реестры, корректировки, выплаты или provider transfers, дата `as_of`, расшифровка комиссий и налогов, экспорт, оспаривание; никаких fake revenue и внутренних «денег к выводу» в immediate split mode.

**Buyer → Order:** master order со строками по продавцам, независимая доставка, статус оплаты/возврата, юридические данные продавца, подтверждённые цены/условия и история.

**Admin → Finance/Disputes:** reconciliation queue, provider anomalies, dispute attachments, maker-checker, step-up for bank detail approval, blocked payouts alerts; только аудитируемые разрешённые операции.

Все экраны — по действующей Design System, auth browser E2E, реальным API; overlay screenshot не заменяет работающего кода.

## 13. Реализация по этапам и gates

### P0 — G0: подтверждение бизнес-правил (обязательный блокер)
1. Юрист/финансы утверждают LEG-01..09, seller/buyer договоры, товары, роль платформы, KKT, НДС, сроки претензий.
2. Получить письменный capabilities response и sandbox у PSP; выбрать MODE A или MODE B; определить комиссию и выплату.
3. Утвердить оферту доставки seller-fulfilled, допустимые delivery promises, SLA, перевозчиков/собственного курьера.
4. Записать итог как `ADR-001 ACCEPTED`, изменить открытые параметры в конфигурации; пока `PROPOSED` — реальные финансовые действия запрещены.

### P1 — G1: order snapshots/fulfillment data model
- Инвентаризация имеющихся B2C orders/B2B reserves/модерации.
- Additive Alembic, frozen seller allocations, status machine, tenant permissions, delivered quantity tracking, state/event log, API contracts.
- Integration tests ORD-01..ORD-13, особенно multi-seller/order isolation, race cancellation vs packing.

### P2 — G2: возвраты ORD-14..ORD-16
- `return_cases`, `return_items`, atomic qty guard, independent refund state, inspections and restock once.
- Unit/PG concurrency/E2E tests, уникальные складские operations, аудит. Закрывать отдельные ORD только после реальных PostgreSQL evidence.

### P3 — G3: provider outage ORD-17
- Carrier adapter(s), provider operation status, retries, dead letter, alerting, status reconciliation. Проверка fault injection с восстановлением.

### P4 — G4: payment + fiscal integration FIN-01..FIN-06
- PSP adapter + hosted checkout + verified signed events + refund and chargeback.
- Provider sandbox, receipt status, versioned tax+commission, idempotency and reconciliation.

### P5 — G5: ledger/settlement FIN-07..FIN-13
- Accounting-model-specific immutable double-entry, actual PSP distribution/payout mapping, cut-off windows, step-up bank changes, cross-tenant controls, refund/settlement race.
- Provider reconciliation files against ledger, auditor sign-off, reconciliation alarms.

### P6 — G6: fullstack security/UI/DR/QA
- Seller/Buyer/Admin real authenticated E2E, visual parity Stitch, contract testing, restore PITR, failure drills and alerts, merchant onboarding, release manifests.
- После последней модификации три независимых PASS на одном commit SHA + image digests + code freeze; нет обязательных `NOT_RUN/BLOCKED`.

### Важные зависимости
`LEGAL/PSP contract -> fiscal schema -> production payment`; `seller order snapshots -> returns`; `verified return claim -> refund`; `inspection -> restock`; `PSP register -> settlement reconciliation`; `seller legal verification -> payment splits/payouts`.

## 14. Блокеры и owner decisions

| ID | Необходимое решение | Владелец | Gate |
|---|---|---|---|
| D-01 | B2C-only first, или добавить B2B покупателей по счёту | Product | До UX/checkout |
| D-02 | Точная роль платформы и договора с продавцами, покупателями | Legal | До платежей |
| D-03 | Есть ли признаки посреднической цифровой платформы и реестровые обязанности 289-ФЗ | Legal | До публичного запуска |
| D-04 | Выбор PSP и коммерческое одобрение компаний/ИП, split и чеков | Finance/PSP | До PSP integration GA |
| D-05 | Immediate split или provider-held delayed settlement | Finance/PSP/Legal | До ledger/payouts |
| D-06 | Кто выпускает чек, как фискализируется доставка, налог/суммы | Accountant/PSP | До receipt test |
| D-07 | Версионируемые ставки НДС/комиссии, перерасчёт при возврате | Accountant/Product | До FIN-01/02/06 |
| D-08 | Кто несёт стоимость доставки и обратной доставки, SLA | Product/Legal/Seller | До carrier fulfillment |
| D-09 | Порядок претензий, срок законного возврата денег и одобрения | Legal/Operations | До ORD-14 |
| D-10 | Сценарии chargeback after payout, удержаний и взыскания | PSP/Finance/Legal | До FIN-05/10/13 |
| D-11 | Поставщик KYB/проверка ЕГРЮЛ/ЕГРИП и маркеров товара | Operations/Legal | До seller onboarding GA |
| D-12 | Точный contract/schema для B2C/B2B/Finance boundaries | Tech lead | До миграций |

## 15. Подтверждение принятия ADR

- [ ] Product Owner утверждает продавца стороной договора купли-продажи и seller-fulfilled модель.
- [ ] Юрист подтверждает платёжно-агентскую роль платформы, применимость 289/290-ФЗ, оферты и возвраты.
- [ ] Бухгалтер подтверждает модели НДС/54-ФЗ, чеков, комиссий и payout receipts.
- [ ] PSP предоставляет sandbox, commercial agreement, provider capability matrix, webhook security и sample реестры.
- [ ] Техлид подтверждает миграционный план, владельцев данных, API, ledger semantics и тестовые данные.
- [ ] Operations подтверждает SLA, эскалацию, restores, финансовые reconciliation runbooks.

**Итоговый статус:** `PROPOSED` до всех указанных подписаний/подтверждений. FIN/ORD-контракты выше — целевые и требуют актуализации после PSP onboarding. Источники и точная QA-mapping есть в дополнительном `planning/ACCEPTANCE_ORD_FIN.md`.
