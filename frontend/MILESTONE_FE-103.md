# FE-103 — recovery token gate

SF-12 теперь проверяет наличие recovery token на серверном route level и передаёт в клиент только boolean-факт. Сам token не читается компонентом, не логируется и не попадает в UI/аналитику; без него форма не показывается.

Проверка: `npx --yes pnpm@9.15.5 --filter @neomarket/storefront typecheck` — успешно.
