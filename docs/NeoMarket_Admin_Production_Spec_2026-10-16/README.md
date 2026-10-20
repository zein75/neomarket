# NeoMarket Admin — Production Blueprint v1.0

**Дата:** 2026-10-16. **Исходный snapshot:** `neomarket-full-audit-2026-10-16.zip`. **Статус документа:** proposed implementation specification; NO-GO до выполнения release gates.

## Что читать и в каком порядке

1. [`MASTER_SPEC.md`](MASTER_SPEC.md) — продуктовые требования, архитектурные решения, глобальные инварианты, жизненные циклы.
2. [`audit/CURRENT_STATE.md`](audit/CURRENT_STATE.md) — подтверждённый обзор конкретных файлов в текущем исходном коде, степени достоверности.
3. [`audit/RISK_REGISTER.csv`](audit/RISK_REGISTER.csv) — реестр дефектов/рисков P0–P3.
4. [`architecture/DOMAIN_AND_DATA.md`](architecture/DOMAIN_AND_DATA.md) — модели, владение данными, схема таблиц, транзакции, события.
5. [`architecture/WORKFLOWS.md`](architecture/WORKFLOWS.md) — модерация, категории, жалобы, апелляции, управление продавцами.
6. [`contracts/admin-target.openapi.yaml`](contracts/admin-target.openapi.yaml) — **целевые** API. Не являются описанием уже реализованных маршрутов.
7. [`contracts/EVENTS_AND_ERRORS.md`](contracts/EVENTS_AND_ERRORS.md) — event envelope, идемпотентность, коды ошибок.
8. [`design/ADMIN_UI_SPEC.md`](design/ADMIN_UI_SPEC.md) — экраны, компоненты, дизайн-система, визуальный QA.
9. [`design/admin-stitch-reference.png`](design/admin-stitch-reference.png) — копия исходного Admin Stitch reference.
10. [`security/SECURITY_AND_COMPLIANCE.md`](security/SECURITY_AND_COMPLIANCE.md) — OIDC/MFA, RBAC, аудит, threats.
11. [`qa/ACCEPTANCE_MATRIX.csv`](qa/ACCEPTANCE_MATRIX.csv) — тест-кейсы с трассировкой.
12. [`qa/RELEASE_GATES.md`](qa/RELEASE_GATES.md) — обязательные критерии итераций и production.
13. [`planning/IMPLEMENTATION_PLAN.md`](planning/IMPLEMENTATION_PLAN.md) — зависимости, последовательность изменений, миграции.
14. [`planning/CODEX_IMPLEMENTATION_PROMPT.md`](planning/CODEX_IMPLEMENTATION_PROMPT.md) — готовый запрос агенту.
15. [`migrations/MIGRATION_BLUEPRINT.md`](migrations/MIGRATION_BLUEPRINT.md) — expand/migrate/contract, rollback, backfill.

## Статусы

- `IMPLEMENTED_IN_SOURCE`: подтверждено статическим чтением исходников; НЕ означает успешных интеграционных тестов.
- `PARTIAL`: присутствует часть процесса.
- `MISSING`: соответствующая возможность в изученных компонентах не обнаружена.
- `PROPOSED`: новый контракт/решение для реализации.
- `BLOCKED`: невозможно завершить без внешнего решения или окружения.
- `PASS`: только с артефактами успешной фактической проверки.

## Принцип источников истины

Актуальная утверждённая production-спецификация и согласованные бизнес-решения → текущие Stitch HTML/PNG для визуальной части → реальная архитектура NeoMarket → текущие маршруты API. Старые каноны и старые схемы API не использовать в качестве обязательных требований. Расхождения между этим blueprint и бизнес-политикой разрешать отдельными ADR, а не молча.

## Запреты

- Нельзя выдавать желаемый API за существующий.
- Нельзя имитировать успешную модерацию, блокировку или создание категории в браузере.
- Нельзя объявлять PASS по тестам, которые не выполнялись.
- Нельзя подвергать реальные товары/продавцов разрушительным E2E-проверкам.
- Нельзя обещать абсолютное отсутствие ошибок: release gate должен опираться на измеримые доказательства.
