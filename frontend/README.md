# NeoMarket frontend

Первый исполняемый срез по `docs/NeoMarket_Frontend_Production_Spec_2026-10-15`.

## Что реализовано

- pnpm workspace с отдельными `storefront`, `seller` и `admin` app-shells;
- shared TypeScript DTO, auth-типы и design tokens;
- storefront SF-01/SF-02/SF-06/SF-15 preview: навигация, поиск, категории, карточки, корзина и безопасные состояния;
- удалённые позиции отображаются недоступными и не входят в итог;
- responsive brutalist UI на токенах `docs/design-system` (Space Grotesk / Manrope / Space Mono, cobalt/lime/coral, 2px borders, hard shadows);
- metadata, skip-link, keyboard-friendly controls, focus-visible через native controls и reduced-motion-safe layout.

## Ограничение текущего среза

Backend BFF-контракт из `docs/.../contracts/bff.openapi.yaml` помечен спецификацией как TO-BE. Поэтому storefront сейчас помечен `preview / read-only`: в нём нет фиктивного подтверждения заказа, оплаты, склада или модерации. Подключение реальных данных выполняется через `@neomarket/api-client` после согласования allowlist операций и серверной session policy.

## Запуск

Требуется Node LTS и pnpm `9.15.5`:

```bash
corepack enable
pnpm install --frozen-lockfile
pnpm --filter @neomarket/storefront dev
```

Для локального запуска с Docker B2C задайте server-only переменные до старта Next.js
(не используйте `NEXT_PUBLIC_*` для внутренних URL):

```powershell
$env:NODE_ENV = 'development'
$env:NEOMARKET_PUBLIC_ORIGIN = 'http://127.0.0.1:3000'
$env:NEOMARKET_B2C_URL = 'http://127.0.0.1:8001'
pnpm --filter @neomarket/storefront dev -- --port 3000
```

Без `NEOMARKET_B2C_URL` BFF намеренно отвечает `503`, а при несовпадении
`NEOMARKET_PUBLIC_ORIGIN` mutation-запросы намеренно отклоняются `403`.

Проверки с установленными зависимостями:

```bash
pnpm -r typecheck
pnpm -r build
```

В этой среде pnpm и lockfile ещё не установлены, поэтому команды проверки отмечены как NOT TESTED.
