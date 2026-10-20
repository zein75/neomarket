# Milestone FE-092 — browser cache isolation

- Account/session, product detail and category detail client fetches now explicitly use `cache: no-store`.
- This aligns browser behavior with BFF no-store headers and prevents stale identity/private/detail data after changes.

Verification:

- Storefront typecheck passed.
