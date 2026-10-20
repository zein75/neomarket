# FE-095 — catalog fetch deadline

Live catalog requests теперь имеют bounded deadline 5 секунд вместе с retry-попыткой. Abort при размонтировании не меняет UI, а именно timeout переводит каталог в recoverable error с кнопкой повторной загрузки; бесконечное loading исключено.

Проверка: `npx --yes pnpm@9.15.5 --filter @neomarket/storefront typecheck` — успешно.
