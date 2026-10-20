# Milestone FE-058 — authoritative cart-item removal

- Added `DELETE /api/storefront/cart/items/{itemId}` BFF route with UUID validation, guest-session isolation, CSRF token and trusted-origin checks, bounded timeout and request correlation.
- Added `removeGuestCartItem()` to the API client; it returns the complete normalized `CartDto` from the server instead of `void` or a locally recalculated result.
- Clear-cart semantics remain unchanged (`204`), while single-item removal follows the contract's updated-cart response.

Verification:

- Full frontend recursive typecheck passed.
