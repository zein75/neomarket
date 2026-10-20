# FE-099 — storefront route reachability

Header actions `Войти` and `Избранное` теперь ведут на реальные `/login` и `/favorites` маршруты вместо preview-only toast. Для anchor-вариантов сохранены design-system focus ring, цвет и inline-flex layout.

Проверка: `npx --yes pnpm@9.15.5 --filter @neomarket/storefront typecheck` — успешно.
