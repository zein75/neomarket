# FE-133 — contradictory cart validation guard

`CartValidation.isValid` теперь false, если payload одновременно содержит `is_valid=true` и хотя бы один валидный blocking issue. Checkout остаётся закрытым при противоречивом server response.

Проверка: `npx --yes pnpm@9.15.5 --filter @neomarket/api-client typecheck` — успешно.
