# FE-100 — checkout operation status route

Добавлен SF-08 `/checkout/status/[operationId]` с `noindex`. Страница fail-closed: не показывает выдуманный payment/order result и не трактует pending/unknown как completed, пока backend не предоставит проверенную correlation-связь.

Проверка: `npx --yes pnpm@9.15.5 --filter @neomarket/storefront typecheck` — успешно.
