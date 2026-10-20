# Milestone FE-065 — cart contract casing normalization

- Cart API normalization now accepts the approved snake_case service payload and camelCase BFF payload.
- Item fields, availability reasons, totals and validation issues are normalized into one typed client model.
- Unknown/malformed cart items are discarded rather than rendered as fabricated data.

Verification:

- Full frontend recursive typecheck passed.
