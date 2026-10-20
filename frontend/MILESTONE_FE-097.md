# FE-097 — authoritative pagination gate

Кнопка перехода на следующую страницу каталога теперь ориентируется на размер полученной серверной страницы (`catalog.length`), а не на результат локального текстового фильтра. Это не блокирует pagination из-за локального отображения и сохраняет URL-driven query state.

Проверка: `npx --yes pnpm@9.15.5 --filter @neomarket/storefront typecheck` — успешно.
