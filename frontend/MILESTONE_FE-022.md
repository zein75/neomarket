# Milestone FE-022 — product detail

- Added `/product/[id]` public route.
- Added fixed-origin BFF route `/api/storefront/products/[productId]`.
- Product IDs are validated as UUIDs before any upstream request.
- Detail UI has loading, unavailable and malformed-response states.
- Preview never fabricates product price, stock or moderation status.

Verification: syntax check pending; live product contract remains gated by `NEXT_PUBLIC_ENABLE_LIVE_CATALOG`.
