# FE-132 — immediate catalog retry abort

Catalog retry теперь немедленно прекращается, если `AbortSignal` уже отменён перед backoff. Navigation/unmount больше не ждёт искусственный retry timer.

Проверка: `npx --yes pnpm@9.15.5 --filter @neomarket/storefront typecheck` — успешно.
