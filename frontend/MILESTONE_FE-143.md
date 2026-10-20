# FE-143 — trim-aware cart identity validation

Cart item normalization теперь отклоняет whitespace-only `skuId`, `productId` и `name`, согласуя cart identity guard с catalog/detail DTO rules.

Проверка: `npx --yes pnpm@9.15.5 --filter @neomarket/api-client typecheck` — успешно.
