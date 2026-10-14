# Проверка комплекта документации (2026-10-14)

## Что проверено фактически

- Три самостоятельных целевых OpenAPI 3.1 YAML успешно разобраны (`http-b2b`, `http-b2c`, `http-admin`).
- У каждой операции есть явная security declaration и responses; у всех `/internal/v1` одновременно требуется `mutualTLS` и `serviceBearer`; 15 операций B2B, 20 операций B2C, 10 операций Admin — итого 45 целевых HTTP operations.
- Три event JSON Schema имеют корректный Draft 2020-12 и проходят schema check; реальные **примеры форматов**, созданные для целевого контракта, валидны для product.created и moderation.approved.
- Матрица 26 baseline рисков имеет уникальные ID, содержит mapped requirement/test/step и проверяет присутствие упомянутых тестов в `qa/ACCEPTANCE_TEST_PLAN.md`.
- Все локальные конкретные файлы, перечисленные в README, существуют; markdown документы не пустые.

## Чего этот static smoke-test НЕ проверяет

- Ни одна из предложенных функций не была реализована/запущена в существующем NeoMarket репозитории.
- Не выполнялись production CI, integration tests на Postgres/Redis, fault injection, нагрузочные/DR испытания или DAST.
- Базы `on_hand`, `reservation_lines_v2`, `moderation_tickets_v2` существуют только как **blueprint**; нет реальных Alembic revision и preflight на текущих данных.
- Нельзя заявлять, что все возможные новые продуктовые сценарии (PSP/логистика/возвраты/поставщики) покрыты реализацией: они требуют решений владельца бизнеса и дополнительных адаптеров.
- Сгенерированные целевые HTTP OpenAPI — новая **цель разработки**, не репликация старых канонов, не live OpenAPI работающих сервисов. Конечный live-contract diff будет выполнен после реализации.

## Команда повтора

```bash
python -m pip install pyyaml jsonschema referencing
python qa/validate_spec.py .
```

Ожидаемое: `PASS YAML/route security`, `PASS JSON schema syntax`, `PASS sample product.created`, `PASS sample moderation.approved`, `PASS risk mapping`, `PASS spec document checks`.
