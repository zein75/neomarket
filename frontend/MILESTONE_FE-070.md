# Milestone FE-070 — image placeholder safety

- Product cards now fall back to `/design-system/catalog.png` when an upstream DTO omits `imageUrl`.
- The fallback keeps meaningful product `alt` text and prevents broken/undefined image sources.
- This follows the spec's requirement to tolerate products without an image without inventing product media.

Verification:

- Storefront typecheck passed.
