# Milestone FE-033 — typed cart client

- Added Cart DTOs matching the reviewed B2C `CartResponse` shape.
- Added server-boundary client methods `getGuestCart` and `clearGuestCart`.
- Normalization rejects malformed cart lines and preserves `unavailable_reason`.
- DELETE requires the synchronizer CSRF token and never treats an error response as success.

Verification: esbuild syntax check — PASS. Live PostgreSQL/Redis integration — NOT TESTED.
