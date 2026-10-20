# Milestone FE-091 — shared catalog runtime validation

- `getCatalog()` now normalizes and validates the upstream response instead of casting arbitrary JSON.
- Items require id/title, finite non-negative price, supported currency and known availability.
- Cursor and total metadata support both snake_case and camelCase contract spellings.
- Optional image/stock fields are included only when valid, preserving exact optional TypeScript semantics.

Verification:

- `@neomarket/api-client` typecheck passed.
