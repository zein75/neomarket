# FE-112 — safe checkout status refresh

SF-08 получила ручное действие «Обновить статус». Оно повторно открывает тот же `operationId`, не генерирует новый checkout attempt/idempotency key и не переводит pending/unknown в success без backend evidence.

Проверка: `npx --yes pnpm@9.15.5 --filter @neomarket/storefront typecheck` — успешно.
