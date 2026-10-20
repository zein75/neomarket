# Milestone FE-066 — meaningful image alternatives

- Product cards now expose the validated product title as image `alt` text.
- Product detail images use the validated title and expose availability changes with `aria-live`.
- Design-system placeholders remain available when the upstream image is absent, without making the image content inaccessible.

Verification:

- Empty `alt` attributes are no longer used for product content images.
- Storefront typecheck passed.
