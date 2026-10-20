# FE-127 — safe cart validation issue values

`CartValidationIssue.oldValue/newValue` теперь проходят runtime guard: разрешены только string или finite number. Объекты, `NaN` и `Infinity` отбрасываются и не попадают в user-facing price-change сообщения.

Проверка: `npx --yes pnpm@9.15.5 --filter @neomarket/api-client typecheck` — успешно.
