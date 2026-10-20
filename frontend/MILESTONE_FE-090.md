# Milestone FE-090 — authoritative catalog availability

- Live catalog normalization now maps the backend availability enum directly.
- `removed` and `unavailable` receive explicit non-orderable labels and cannot be added to cart.
- An unknown explicit availability value causes the item to be dropped; only absent legacy availability may use the validated `in_stock` fallback.
- Category is preserved from the upstream DTO when supplied.

Verification:

- Storefront typecheck passed.
