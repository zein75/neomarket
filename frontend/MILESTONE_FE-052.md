# Milestone FE-052 — public SEO boundary

- Added canonical metadata and a stable metadata base for public storefront URLs.
- Added Open Graph website metadata without inventing product-level facts.
- Robots rules now explicitly allow public catalog/product paths and disallow private pages plus all internal `/api` and `/bff` routes.
- Existing sitemap remains limited to approved public entry points; private/cart/checkout routes are not advertised.

Verification:

- Storefront typecheck passed.
- Storefront production build passed (27 routes).
