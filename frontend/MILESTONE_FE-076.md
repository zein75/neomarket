# Milestone FE-076 — currency-aware product pricing

- Product cards format prices using the DTO currency instead of assuming RUB.
- Product detail accepts and validates `RUB`, `EUR` or `USD`; absent currency remains a preview-only RUB fallback.
- No discounts, conversions or client-side price adjustments are introduced.

Verification:

- Full frontend recursive typecheck passed.
