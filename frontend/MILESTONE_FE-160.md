# FE-160 — Checkout validation snapshot application

## Delivered

- `validateGuestCart` responses now replace the local cart map and authoritative snapshot before displaying issues.
- Price, stock, quantity, unavailable lines, and subtotal therefore refresh from the same server response that gates checkout.
- Preview mode no longer performs a misleading cart validation request; it explains that checkout requires live cart API.

## Verification

- Storefront typecheck remains the required check for this increment.
