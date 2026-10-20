# FE-104 — login recovery reachability

Login form теперь содержит явную ссылку на `/reset-password`, сохраняя shared auth design-system и fail-closed submit. Компонент структурирован без изменения правила: auth BFF не вызывается до подтверждения backend-контракта.

Проверка: `npx --yes pnpm@9.15.5 --filter @neomarket/storefront typecheck` — успешно.
