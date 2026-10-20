# Milestone FE-068 — URL category filter

- Added bounded `category` query state independent from full-text `q`.
- Category is preserved in canonical URL, validated/truncated at the search boundary and forwarded to the BFF.
- Changing category resets pagination to page 1.
- Added responsive category control using design-system borders, typography and focus treatment.

Verification:

- Storefront typecheck passed.
