# FE-122 — catalog image loading performance

Карточки каталога используют `loading="lazy"` и `decoding="async"`; fallback на design-system asset и alt-тексты сохранены. Initial viewport больше не ждёт загрузки всех изображений страницы.

Проверка: `npx --yes pnpm@9.15.5 --filter @neomarket/storefront typecheck` — успешно.
