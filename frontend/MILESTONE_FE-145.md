# FE-145 — non-empty stock label normalization

Catalog `stockLabel` теперь сохраняется только при непустом trimmed text. Whitespace-only labels отбрасываются, чтобы карточка не показывала пустой status line.

Проверка: `npx --yes pnpm@9.15.5 --filter @neomarket/api-client typecheck` — успешно.
