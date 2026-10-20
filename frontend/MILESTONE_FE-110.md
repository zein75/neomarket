# FE-110 — typed cart validation feedback

Checkout validation теперь отображает тип server-authoritative конфликта (`PRICE_CHANGED`, `OUT_OF_STOCK`, `QUANTITY_REDUCED`, `PRODUCT_BLOCKED`, `PRODUCT_DELETED`) вместе с сообщением backend. Неизвестный тип безопасно получает общий fallback, а checkout не отправляется.

Проверка: `npx --yes pnpm@9.15.5 --filter @neomarket/storefront typecheck` — успешно.
