# FE-117 — legal sitemap coverage

Sitemap теперь включает публичные `/legal/terms`, `/legal/privacy` и `/legal/cookies` с низкой частотой обновления. Private, auth, checkout status и query-driven search routes остаются вне sitemap.

Проверка: `npx --yes pnpm@9.15.5 --filter @neomarket/storefront typecheck` — успешно.
