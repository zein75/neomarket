# FE-105 — private app active navigation semantics

Seller и Admin sidebar navigation теперь выставляет `aria-current="page"` для активного раздела. Навигация остаётся fail-closed и не меняет доступ к данным; стили private apps и design-system сохранены.

Проверка: `npx --yes pnpm@9.15.5 -r typecheck` — успешно для всех workspace packages/apps.
