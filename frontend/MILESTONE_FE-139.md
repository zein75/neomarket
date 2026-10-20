# FE-139 — CategoryDetail optional field guard

`isCategoryDetailDto` теперь принимает `description` только как string; неожиданные object/number payloads отклоняются до render. `product_count` сохраняет non-negative integer guard.

Проверка: api-types и storefront typecheck — успешно.
