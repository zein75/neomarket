# Milestone FE-035 — private buyer route shells

- Added `/account`, `/account/addresses`, `/account/orders/[id]` and `/favorites`.
- Each route is `noindex` and checks same-origin `/bff/session`.
- Guest, unavailable and authenticated-but-not-yet-wired states are explicit.
- No private data, order status or ownership is fabricated in the UI.

Verification: syntax check pending; session integration requires the approved BFF session service.
