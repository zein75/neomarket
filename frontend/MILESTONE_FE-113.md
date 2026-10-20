# FE-113 — orders navigation privacy boundary

Header `Заказы` теперь ведёт на `/account/orders`, где всегда выполняется `AccountGate`. Убран локальный preview-путь, обходивший buyer session boundary при навигации с главной страницы.

Проверка: `npx --yes pnpm@9.15.5 --filter @neomarket/storefront typecheck` — успешно.
