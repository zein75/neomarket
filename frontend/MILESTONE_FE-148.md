# FE-148 — production build after contract hardening

Полный `npx --yes pnpm@9.15.5 -r build` успешно собрал admin, seller и storefront после DTO/availability/image guards. Next.js сообщил только существующие autoprefixer warnings для `align-items: end`; сборка завершилась успешно.
