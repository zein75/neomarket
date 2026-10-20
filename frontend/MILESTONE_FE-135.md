# FE-135 — cart empty-state styling

Пустая корзина больше не выглядит как blank area: `.cart-list:empty` получает paper/surface panel, hard border и design-system message «Корзина пуста» с безопасной подсказкой добавить позиции из каталога.

Проверка: `npx --yes pnpm@9.15.5 --filter @neomarket/storefront typecheck` — успешно.
