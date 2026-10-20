# FE-134 — non-empty cart identity guard

Cart normalization теперь отбрасывает items с пустыми `skuId`, `productId` или `name`; пустой cart id не сохраняется. Это предотвращает key collisions и неинформативные строки в UI.

Проверка: `npx --yes pnpm@9.15.5 --filter @neomarket/api-client typecheck` — успешно.
