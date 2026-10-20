# FE-093 — browser-side fetch deadlines

Добавлен защитный дедлайн 4 секунды для клиентских запросов session, product и category. Таймер очищается при размонтировании, а именно таймаут переводит интерфейс в безопасное состояние ошибки/недоступности вместо бесконечного loading/checking.

Проверка: `npx --yes pnpm@9.15.5 --filter @neomarket/storefront typecheck` — успешно.
