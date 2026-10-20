# Milestone FE-059 — authoritative cart validation

- Added `POST /api/storefront/cart/validate` BFF route with guest-session isolation, CSRF/origin protection, timeout and request correlation.
- Added typed `CartValidation` and issue types covering `PRICE_CHANGED`, `OUT_OF_STOCK`, `QUANTITY_REDUCED`, `PRODUCT_BLOCKED` and `PRODUCT_DELETED`.
- Added `validateGuestCart()` API client operation; checkout can now consume server validation before any order mutation.
- No payment or order success is fabricated by this slice.

Verification:

- Full frontend recursive typecheck passed.
