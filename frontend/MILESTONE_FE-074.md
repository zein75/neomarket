# Milestone FE-074 — detail availability enum guard

- Product detail runtime validation now accepts only `available`, `unavailable` or `removed` when an availability field is present.
- Unknown statuses fail closed into the existing safe error state instead of being treated as orderable.

Verification:

- `@neomarket/api-types` typecheck passed.
