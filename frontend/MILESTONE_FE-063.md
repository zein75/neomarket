# Milestone FE-063 — detail BFF error consistency

- Product detail and category list/detail BFF routes now return normalized `application/problem+json` errors.
- Detail proxy responses carry the correlation ID and remain `no-store`.
- UUID validation failures, missing upstream configuration and timeout/unavailable states share the same safe contract as catalog/cart.

Verification:

- Storefront typecheck passed.
