# FE-094 — checkout validation single-flight guard

Checkout cart validation теперь защищена single-flight guard: повторный submit во время активной server-side проверки не запускает второй запрос. Состояние сбрасывается в `finally`, поэтому recoverable ошибка не оставляет форму заблокированной навсегда.

Проверка: `npx --yes pnpm@9.15.5 --filter @neomarket/storefront typecheck` — успешно.
