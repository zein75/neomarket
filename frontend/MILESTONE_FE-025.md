# Milestone FE-025 / FE-013 / FE-014

## Scope

Added App Router storefront routes and public SEO metadata while keeping all privileged and transactional operations behind the server boundary.

## Implemented

- `/catalog`, `/cart`, `/checkout`, `/account/orders` route entrypoints;
- checkout form with preserved local values and explicit non-submission preview state;
- BFF catalog route with fixed `NEOMARKET_B2C_URL`, bounded timeout, request ID propagation and query allowlist;
- `robots.txt` disallowing private routes and `/bff`;
- `sitemap.xml` containing only approved public routes;
- `.env.example` with server-only configuration and no credentials.

## Verification

- esbuild syntax check for Storefront, BFF, robots and sitemap — PASS.
- Next/pnpm build — NOT TESTED: pnpm and lockfile are not installed in this environment.

## Known limitations

The BFF route is ready for the existing B2C `/api/v1/products` read endpoint, but the UI still uses the design-system preview fixture until the runtime DTO is reconciled with the BFF contract and contract tests are added. Checkout, payment and order mutation remain intentionally disabled.
