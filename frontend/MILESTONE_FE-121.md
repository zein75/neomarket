# FE-121 — broken image fallback

Catalog cards и product detail теперь заменяют broken image на `/design-system/catalog.png` без повторного error loop. Original `alt` и availability контент сохраняются, поэтому layout не ломается при 404/битом asset URL.

Проверка: `npx --yes pnpm@9.15.5 --filter @neomarket/storefront typecheck` — успешно.
