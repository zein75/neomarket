# Milestone FE-079 — strict cart numeric contract

- Cart normalization now requires finite numeric values for unit price, quantity, line total and available quantity.
- Quantities must be positive; monetary and stock values cannot be negative.
- Invalid items are dropped instead of becoming zero-priced or zero-quantity UI rows.

Verification:

- `@neomarket/api-client` typecheck passed.
