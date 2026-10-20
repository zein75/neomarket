# Milestone FE-064 — runtime detail DTO guards

- Added `ProductDetailDto` and `CategoryDetailDto` contracts with runtime validators in `@neomarket/api-types`.
- Product and category detail screens now reject malformed payloads instead of casting arbitrary dictionaries.
- Prices are accepted only as finite non-negative numbers; stock flags, names and counts are type-checked before rendering.
- Invalid upstream data enters the existing safe error state and does not create a fabricated product/category view.

Verification:

- Full frontend recursive typecheck passed.
