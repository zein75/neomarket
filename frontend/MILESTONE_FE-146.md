# FE-146 — authoritative availability requirement

Storefront live catalog больше не угадывает `available`, если backend не прислал `availability` или boolean `in_stock`. Неполный availability payload отбрасывается до render; server authority остаётся единственным источником статуса.

Проверка: `npx --yes pnpm@9.15.5 --filter @neomarket/storefront typecheck` — успешно.
