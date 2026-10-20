# Milestone FE-054 — private app cache isolation

- Seller and Admin root layouts now force dynamic rendering with `revalidate = 0` and `fetchCache = force-no-store`.
- Private screens remain fail-closed placeholders until server-side identity contracts are connected; no static shared HTML is generated for those routes.
- Existing noindex robots metadata is preserved.

Verification:

- Seller typecheck passed.
- Admin typecheck passed.
- Seller production build passed; all application routes are dynamic (`ƒ`).
- Admin production build passed; all application routes are dynamic (`ƒ`).
