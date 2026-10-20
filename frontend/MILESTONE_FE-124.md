# FE-124 — checkout validation deadline

CSRF fetch и `cart.validate` теперь выполняются под общим 5-секундным AbortController. Таймер очищается в `finally`; timeout не создаёт заказ, не повторяет POST и переводит UI в recoverable error.

Проверка: `npx --yes pnpm@9.15.5 --filter @neomarket/storefront typecheck` — успешно.
