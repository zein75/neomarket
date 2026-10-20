# FE-147 — ProductDetail authoritative availability

`isProductDetailDto` теперь требует `availability` или boolean `in_stock`. Detail payload без server availability signal не renderится как доступный по умолчанию.

Проверка: api-types и storefront typecheck — успешно.
