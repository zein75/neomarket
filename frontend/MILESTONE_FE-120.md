# FE-120 — remove synthetic storefront telemetry

Убраны фиксированные `NODE`, `SYS_LATENCY: 14MS` и `LIVE DISPATCH` claims. System strip и hero card теперь показывают только честный режим `PREVIEW`/`LIVE CATALOG`, `SERVER-READONLY` и `DEMO`/`READ` без выдуманных runtime metrics.

Проверка: `npx --yes pnpm@9.15.5 --filter @neomarket/storefront typecheck` — успешно.
