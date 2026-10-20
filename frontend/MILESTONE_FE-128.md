# FE-128 — fail-closed cart validation snapshot

`CartValidation.isValid` теперь может быть `true` только при наличии object cart snapshot и явного backend-флага валидности. Неполный/malformed response автоматически блокирует checkout.

Проверка: `npx --yes pnpm@9.15.5 --filter @neomarket/api-client typecheck` — успешно.
