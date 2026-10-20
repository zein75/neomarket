# Milestone FE-089 — price requires currency

- Product detail runtime validation now rejects a numeric price when no supported currency is present.
- Detail UI renders price only when both validated price and currency exist.
- This prevents a currency guess from turning an authoritative amount into a misleading display.

Verification:

- Full frontend recursive typecheck passed.
