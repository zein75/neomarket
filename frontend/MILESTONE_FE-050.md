# Milestone FE-050 — URL-driven catalog controls

- Catalog search is preserved as the canonical `q` query parameter and sanitized to 200 characters.
- Supported sorting is explicit and typed: `popularity`, `price_asc`, `price_desc`, `new`.
- Search pages validate the incoming sort value and fall back to `popularity` for unknown values.
- Live catalog requests forward the selected sort to the BFF; preview data applies the same price ordering locally.
- The catalog BFF validates and bounds `q`, `category`, `page`, `limit` and `sort` before forwarding them upstream.
- Sorting controls use the existing design-system tokens, hard borders, lime focus ring and responsive layout.

Verification:

- `pnpm --filter @neomarket/storefront typecheck` passed.
- `pnpm --filter @neomarket/storefront build` passed (27 routes).
