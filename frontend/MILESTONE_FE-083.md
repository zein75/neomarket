# Milestone FE-083 — session outage semantics

- AccountGate now distinguishes `401` (anonymous/guest) from `503` (identity boundary unavailable).
- Temporary session outages fail closed with an unavailable message instead of incorrectly presenting a normal login state.
- Valid authenticated and anonymous session payloads remain runtime-validated.

Verification:

- Storefront typecheck passed.
