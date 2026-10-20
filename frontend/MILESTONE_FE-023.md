# Milestone FE-023 — URL search

- Added `/search?q=...` App Router entrypoint.
- Query is bounded to 200 characters before entering the UI/BFF flow.
- Search remains same-origin and uses the existing BFF catalog allowlist.
- Empty/loading/error states remain identical to catalog, preserving visual and accessibility consistency.

Verification: syntax check pending; live BFF integration remains runtime-flagged.
