# FE-131 — cart and checkout indexing policy

`/cart` и `/checkout` теперь имеют `robots: noindex, nofollow`. Guest cart остаётся доступной, но приватные/транзакционные UI routes не публикуются как поисковые страницы.

Проверка: `npx --yes pnpm@9.15.5 --filter @neomarket/storefront typecheck` — успешно.
