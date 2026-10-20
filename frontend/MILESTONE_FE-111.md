# FE-111 — server price change disclosure

При `PRICE_CHANGED` checkout feedback теперь включает authoritative `oldValue → newValue`, если backend их прислал. UI не вычисляет новую цену и не отправляет checkout до повторной проверки.

Проверка: `npx --yes pnpm@9.15.5 --filter @neomarket/storefront typecheck` — успешно.
