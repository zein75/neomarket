# FE-106 — private navigation active styling

Активные Seller/Admin sidebar links теперь визуально выделяются через `[aria-current="page"]`: hard border и hard shadow, coral для Admin и lime для Seller — в соответствии с NeoMarket design-system.

Проверка: `npx --yes pnpm@9.15.5 -r typecheck` — успешно для всех workspace packages/apps.
