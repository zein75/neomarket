# FE-144 — catalog category fallback

Catalog normalization теперь заменяет missing/whitespace-only category на `Каталог`; valid category text сохраняется. Это предотвращает пустые eyebrows и сохраняет стабильный visual hierarchy design-system.

Проверка: api-client и storefront typecheck — успешно.
