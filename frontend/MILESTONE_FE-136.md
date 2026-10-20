# FE-136 — strict catalog pagination metadata

Catalog normalization теперь принимает только non-negative integer `total` и непустой `nextCursor`. Некорректные pagination metadata отбрасываются, чтобы UI не строил неверные переходы.

Проверка: `npx --yes pnpm@9.15.5 --filter @neomarket/api-client typecheck` — успешно.
