# Milestone FE-082 — account session gate correctness

- AccountGate now validates `/bff/session` with the shared `isSessionResponse` runtime guard.
- A valid `authenticated: false` response transitions to the login/guest state instead of leaving the UI stuck in loading.
- Malformed session payloads fail closed to the unavailable state and never reveal private data.

Verification:

- Storefront typecheck passed.
