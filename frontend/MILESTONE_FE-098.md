# FE-098 — deferred catalog search

Ввод в поиске остаётся мгновенным для UI и URL, но live catalog BFF получает `useDeferredValue(query)`. Это уменьшает burst запросов при печати, сохраняя server-authoritative фильтрацию и существующие timeout/retry ограничения.

Проверка: `npx --yes pnpm@9.15.5 --filter @neomarket/storefront typecheck` — успешно.
