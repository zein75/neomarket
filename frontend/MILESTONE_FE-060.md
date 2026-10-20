# Milestone FE-060 — checkout validation handoff

- Checkout now requests a same-origin CSRF token and calls `validateGuestCart()` before any order mutation.
- Validation issues are shown as a recoverable notice; the first authoritative issue message is surfaced without local price/stock recalculation.
- A valid cart still stops at the explicit checkout-operation gate; no payment, order or success state is fabricated.
- Network/CSRF failures leave the user in a safe retryable state.

Verification:

- Storefront typecheck passed.
