# FE-116 — crawler exclusion for sensitive routes

`robots.ts` теперь исключает `/checkout/status`, `/reset-password` и `/maintenance` вместе с существующими private/API routes. Публичные catalog/product/category paths остаются разрешёнными для индексации.

Проверка: `npx --yes pnpm@9.15.5 --filter @neomarket/storefront typecheck` — успешно.
