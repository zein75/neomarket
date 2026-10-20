# FE-102 — orders session boundary

Приватный маршрут `/account/orders` больше не рендерит общий preview напрямую. Он использует `AccountGate`, проверяет same-origin session и fail-closed при 401/503/некорректном payload, не раскрывая чужую историю заказов.

Проверка: `npx --yes pnpm@9.15.5 --filter @neomarket/storefront typecheck` — успешно.
