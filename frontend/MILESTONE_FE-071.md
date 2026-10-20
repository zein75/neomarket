# Milestone FE-071 — validation issue allowlist

- Cart validation normalization now accepts only the five specified issue types.
- Unknown issue codes are dropped instead of being rendered as actionable business states.
- Valid issue messages and optional old/new values remain available to the checkout UI.

Verification:

- `@neomarket/api-client` typecheck passed.
