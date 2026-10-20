# Milestone FE-056 — CSRF origin defense

- Guest-cart `DELETE` now requires both the synchronizer token and a trusted mutation origin.
- Cross-site Fetch Metadata requests are rejected before any upstream call.
- Configured public origin is required for browser requests and compared exactly (trailing slash normalized); requests without an Origin header remain compatible with same-origin non-browser clients while still rejecting `Sec-Fetch-Site: cross-site`.
- Errors remain generic RFC 7807-style JSON and do not expose upstream details.

Verification:

- Storefront typecheck passed.
