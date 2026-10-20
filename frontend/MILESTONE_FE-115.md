# FE-115 — search indexing policy

Маршрут `/search` с произвольными query/filter/sort/page параметрами теперь имеет `robots: noindex, follow`. Это предотвращает crawl/index explosion, сохраняя переходы по внутренним ссылкам и URL-driven UX.

Проверка: `npx --yes pnpm@9.15.5 --filter @neomarket/storefront typecheck` — успешно.
