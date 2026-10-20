# Milestone FE-084 — registration form guard

- Registration now validates password confirmation before entering pending state.
- Mismatch is exposed as an accessible alert and no auth request/placeholder success is created.
- Existing minimum-length and autocomplete constraints remain in place.

Verification:

- Storefront typecheck passed.
