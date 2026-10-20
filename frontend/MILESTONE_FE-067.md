# Milestone FE-067 — URL pagination

- Added bounded, typed `page` query parsing to the search route.
- Catalog URL now preserves `q`, `sort` and `page` as the source of truth.
- Live BFF requests use the corresponding offset; changing sort resets to page 1.
- Previous/next controls use the design-system borders, lime focus treatment and disabled states.

Verification:

- Storefront typecheck passed.
