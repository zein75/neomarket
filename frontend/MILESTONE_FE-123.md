# FE-123 — catalog retry listener cleanup

Retry backoff каталога теперь удаляет `AbortSignal` listener и timer после успешного backoff или abort. Это сохраняет bounded retry semantics и предотвращает накопление обработчиков при частом поиске/фильтрации.

Проверка: `npx --yes pnpm@9.15.5 --filter @neomarket/storefront typecheck` — успешно.
