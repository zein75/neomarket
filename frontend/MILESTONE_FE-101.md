# FE-101 — password reset route coverage

Добавлены SF-11 `/reset-password` и SF-12 `/reset-password/confirm` с design-system auth form. До готовности BFF reset-контракта submit честно остаётся blocked: token не попадает в аналитику, внешние запросы и логи, completion не симулируется.

Проверка: `npx --yes pnpm@9.15.5 --filter @neomarket/storefront typecheck` — успешно.
