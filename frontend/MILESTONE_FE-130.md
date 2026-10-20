# FE-130 — cart reason and image guards

Cart normalization теперь принимает только backend enum для `unavailableReason`; image сохраняется только как object/null. Некорректные reason/image значения не доходят до UI.

Проверка: `npx --yes pnpm@9.15.5 --filter @neomarket/api-client typecheck` — успешно.
