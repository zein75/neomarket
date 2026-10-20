# Milestone FE-020 — categories

- Added public category detail route `/catalog/category/[id]`.
- Added fixed-origin category tree/detail BFF routes.
- Category IDs are validated before upstream requests.
- UI uses explicit loading, blocked preview and unavailable states; no fabricated category metadata.

Verification: syntax check pending; live B2C catalog remains gated by the runtime flag.
