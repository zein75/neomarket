# Milestone FE-078 — strict live catalog price contract

- Live catalog normalization now requires a supported currency (`RUB`, `EUR`, `USD`).
- Prices must be finite non-negative numbers; malformed items are omitted rather than shown with guessed values.
- Missing images still use the design-system placeholder, while price/currency data remains authoritative-only.

Verification:

- Storefront typecheck passed.
