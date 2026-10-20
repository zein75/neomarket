# FE-126 — integer cart item contract

Нормализация cart items теперь принимает только integer minor-unit значения для `unitPriceMinor`, `lineTotalMinor`, `quantity` и `availableQuantity`. Дробные и нечисловые данные отбрасываются до расчёта UI.

Проверка: `npx --yes pnpm@9.15.5 --filter @neomarket/api-client typecheck` — успешно.
