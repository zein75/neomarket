# FE-114 — auth route indexing policy

`/login` и `/register` теперь явно помечены `robots: noindex, nofollow`. Auth UI остаётся доступным пользователям, но не становится поисковой landing-страницей и не создаёт лишние индексируемые точки входа.

Проверка: `npx --yes pnpm@9.15.5 --filter @neomarket/storefront typecheck` — успешно.
