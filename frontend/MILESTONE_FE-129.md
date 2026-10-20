# FE-129 — required cart availability flag

Cart item normalization теперь отбрасывает items без boolean `is_available`. Отсутствующий availability больше не превращается молча в unavailable, поэтому malformed response не влияет на сумму/UX.

Проверка: `npx --yes pnpm@9.15.5 --filter @neomarket/api-client typecheck` — успешно.
