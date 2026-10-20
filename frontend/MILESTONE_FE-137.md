# FE-137 — safe catalog image URL policy

Catalog image URLs теперь допускаются только для same-origin paths (`/…`) или HTTPS. Другие схемы/форматы заменяются на `/design-system/catalog.png` до render.

Проверка: api-client и storefront typecheck — успешно.
