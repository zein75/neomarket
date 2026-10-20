# Milestone FE-049 — admin route shells

- Added `/moderation`, `/audit` and `/reasons` admin routes.
- Added closed-by-default admin navigation and responsive layout using design-system tokens.
- No moderation ticket, claim, heartbeat, decision or audit event is fabricated.
- Routes explicitly communicate OIDC/MFA, RBAC and backend contract blockers.

Verification: syntax check pending; real admin identity and two-moderator integration tests remain required.
