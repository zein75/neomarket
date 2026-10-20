# FE-119 — truthful storefront API status

Footer теперь показывает `preview / read-only` или `live catalog / read-only` на основе фактического `NEXT_PUBLIC_ENABLE_LIVE_CATALOG`. UI не маскирует режим подключения и не заявляет активные checkout/payment capabilities.

Проверка: `npx --yes pnpm@9.15.5 --filter @neomarket/storefront typecheck` — успешно.
