# FE-096 — catalog browser history synchronization

Каталог теперь восстанавливает `q`, `category`, `sort` и `page` из URL при browser back/forward через `popstate`. Значения проходят те же allowlist и bounds, что и обычное состояние UI; неподдерживаемая сортировка и некорректная страница безопасно возвращаются к defaults.

Проверка: `npx --yes pnpm@9.15.5 --filter @neomarket/storefront typecheck` — успешно.
