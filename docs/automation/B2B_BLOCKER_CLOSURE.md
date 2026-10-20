# NeoMarket B2B blocker closure

Дата: 2026-10-20  
Текущий staging release: `b0fd2323d8fa5c6df166018f0e5f7c0cfdb4c565`  
Сервер: `192.168.0.112`  

Этот документ перечисляет только подтверждённые незакрытые требования. Нельзя переводить пункт в `PASS` по наличию кода или документации: для каждого пункта нужен runtime evidence на зафиксированном staging release.

## Уже подтверждено

- Все обязательные контейнеры staging healthy.
- B2B regression: `285 passed, 38 skipped, 0 failed`.
- Ruff, compileall и current OpenAPI checks проходят.
- B2B `/health` и `/ready` отвечают через gateway.
- Boundary checks: неверный login `401`, unauthenticated seller metrics `401`, legacy products `410`, `/internal/*` через gateway `404`.
- Публично опубликованы только ingress-порты Caddy `80/443`; database, Redis, APIs, Mailpit и ClamAV не опубликованы наружу.

Evidence находится в `docs/automation/evidence/staging/` и перечислена в `docs/automation/B2B_STAGING_QA_2026-10-20.md`.

## Closure order

### 1. Test fixture and authenticated staging evidence

**Why:** без изолированной staging fixture нельзя честно выполнить Seller browser flows, UI-03/UI-06/UI-07/UI-08 и часть ID-16.

Нужно:

1. Добавить root-owned, одноразовый QA runner для staging. Он должен создавать пользователей/организации/товары с UUID run id, выдавать credentials только через `0600` artifact владельцу QA и поддерживать cleanup по run id.
2. Запрещать runner в production и не добавлять общий demo/backdoor аккаунт.
3. Установить runner только через существующий root-owned refresh/deployment путь. Не расширять SSH guard до произвольного shell или Docker.
4. Провести три независимых authenticated Playwright runs на одном SHA с trace/screenshot/HTML JSON manifests.

### 2. ID-16: step-up MFA и session fixation

**Current:** MFA endpoint fail-closed (`501 FEATURE_NOT_CONFIGURED`) до выбора identity/MFA provider.

Нужно после утверждения provider/ADR:

1. Подключить реальный staging MFA provider или утверждённый Keycloak step-up flow для Seller identity.
2. Требовать step-up для изменения банковских реквизитов, owner transfer, API keys и иных high-risk mutations.
3. Проверить AMR/ACR, challenge expiry, replay, rate limits, audit event и recovery.
4. Выполнить browser test с pre-login cookie и доказать отсутствие session fixation.

До решения provider пункт остаётся `PARTIAL`; обход через тестовый код запрещён.

### 3. ORD-14..ORD-17: returns, restock and carrier outage

**Current:** merchant of record, delivery owner, return owner, refund authority и restock policy отложены до ADR.

Нужно после ADR:

1. Зафиксировать state machine return request/decision/received и права seller/admin.
2. Добавить append-only return events, `return_items`, ограничения `returned <= delivered` и partial-unit returns.
3. Сделать restock idempotent и защищённым уникальным ключом/row lock.
4. Передавать refund intent в finance service; seller не помечает refund как settled.
5. Добавить carrier/provider adapter, timeout -> recoverable `PENDING`, reconciliation, retry/DLQ и owner escalation alerts.
6. Выполнить ORD-14..ORD-17 на staging с двумя tenants и доказать повтор/конкурентность.

### 4. FIN-01..FIN-13: PSP, ledger and payout

**Current:** finance routes намеренно закрыты явным `501 FEATURE_NOT_CONFIGURED`; fake zero balances и browser-paid state запрещены.

Нужно после утверждения commercial ADR:

1. Утвердить merchant of record, tax/commission policy, settlement window, refund/chargeback authority и PSP sandbox.
2. Подключить PSP adapter с signature verification, timestamp/replay protection и webhook idempotency.
3. Реализовать immutable double-entry ledger и snapshots от accepted master order.
4. Реализовать partial refund, chargeback reversal, payout idempotency, failed-payout pending/reconciliation и cross-tenant 404.
5. Добавить step-up MFA для bank changes и finance RBAC.
6. Выполнить FIN-01..FIN-13, включая concurrent refund/settlement, на provider sandbox.

Без ADR этот блок закрыть нельзя и нельзя подменять PSP локальным mock в release evidence.

### 5. UI-03, UI-06, UI-07, UI-08

Нужно на authenticated staging fixture:

1. Снять Seller desktop 1280 baseline comparison с утверждённым Stitch source; baseline может утвердить только владелец продукта.
2. Выполнить keyboard/focus traversal на login, navigation drawer, all Seller routes и conflict modal.
3. Выполнить axe WCAG 2.2 AA и ручную AT/screen-reader проверку с сохранёнными результатами.
4. Проверить truthful loading/empty/error states при реальных 401/403/404/409/412/429/503 ответах.
5. Не обновлять snapshots только для сокрытия расхождений.

### 6. SEC-11: off-host backup and PITR

Нужно:

1. Утвердить внешний backup target вне staging host и retention/encryption policy.
2. Включить PostgreSQL WAL/PITR, object-storage backup и Keycloak/config metadata backup.
3. Выполнить restore в изолированное окружение; проверить schema, row counts, order-independent checksums и audit-chain.
4. Зафиксировать RPO/RTO, checksum и restore run id в `STAGING_BACKUP_RESTORE.md`.

Локальный restore drill не закрывает off-host PITR requirement.

### 7. SEC-14: degraded dependency drills and alerts

Нужно:

1. Выполнить controlled DB outage drill и проверить bounded retry, fail-closed writes, recovery и alert.
2. После выбора PSP/carrier выполнить соответствующие provider outage drills.
3. Проверить outbox/DLQ backlog, retry exhaustion и notification/escalation path.
4. Сохранить command, timestamps, logs, metrics и outcome; не использовать production data.

## Final release gate

После закрытия пунктов выше нужно:

1. Зафиксировать один Git SHA и image digests.
2. Запустить три независимых полных Playwright/functional manifests на этом SHA.
3. Проверить все required rows в `REQUIREMENT_MATRIX.csv`; ни одного `NOT_RUN`, `BLOCKED` или неполного `PARTIAL`.
4. Запустить seller release verifier с реальной evidence directory.
5. Оставить release status `BLOCKED/PARTIAL`, если любой ADR, provider, restore, manual AT или manifest отсутствует.

Текущий честный статус: **B2B runtime deployed and regression-tested; full Seller/B2B release BLOCKED**.
