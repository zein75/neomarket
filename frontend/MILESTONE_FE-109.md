# FE-109 — catalog filter active state

Chip-фильтры каталога теперь визуально отражают текущий query: `Все категории`, `IoT` и `Робот` получают active state только при соответствующем значении. Это синхронизирует design-system feedback с URL-driven filter state.

Проверка: `npx --yes pnpm@9.15.5 --filter @neomarket/storefront typecheck` — успешно.
