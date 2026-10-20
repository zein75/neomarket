# Admin security architecture and threat model

## Identity / access

- OIDC Authorization Code with PKCE via confidential Next.js BFF; verify exact issuer+audience+nonce+state+signature+JWT TTL and key rotation. Never trust `X-Moderator-Id` except segregated test-only env. Server-side mapping `(iss,sub) -> UUID staff_id`; OIDC `sub` may be opaque string.
- MFA mandatory for all staff; step-up for roles, hard-block, wide category migrations, bulk unpublish and export of sensitive data. Specific `amr`/`acr` mappings are configured for chosen IdP, not hardcoded universal `'mfa'` assumption. Enforce sign-in policy on server, not only redirect UI.
- Opaque session cookie (`__Host-` + HttpOnly/Secure/Path=/ + SameSite); session-bound CSRF token; idle and absolute expiry, revocation, device/session list and authentication audit. Private responses `Cache-Control: private,no-store`; invalidate caches on logout/role change.
- `PermissionGuard` centralized server policy. ABAC: capability, staff scope, object sensitivity, regional applicability, maker-checker conflict, ticket claim. `403` on function, property and object mismatches. All privileged direct API requests denied without service auth.
- Admin gateway private network / conditional access / restricted public exposure; TLS, HSTS, CSP enforcing, CORS exact allowlist, rate limits, resource limits, no internal APIs reachable by buyer/seller clients.

## Threat scenarios to test

| Attack/failure | Defense | Test |
|---|---|---|
| Staff forges/modifies JWT claims | JWKS signature+issuer+audience+exp/nbf+IdP roles; subject mapping | altered signature, wrong issuer/aud/key/roles rejected |
| Auth bypass in local mode | production fail closed; startup validator refuses bypass env; test settings only | staging/prod with `NEOMARKET_DEV_OPEN_ACCESS=true` refused |
| Claims ticket belonging to another moderator | lease token hash + fencing + permission + row lock | simultaneous claim barrier; stale token rejected |
| Approves old product revision | immutable snapshot hash + B2B revision CAS | seller edit during review, approval returns conflict |
| Repeated decision double-publishes | unique Idempotency-Key + request hash + inbox | retry same payload same operation, different payload 409 |
| Taxonomy owner can approve own high impact move | maker-checker server separation | own approval refused |
| Category cycle / lost catalog links | cycle check + FK/path constraints + impact preflight | move parent under child and referenced archive rejected |
| Employee accesses seller docs not in scope | RBAC/ABAC object authorization, redacted API, signed scoped URL | cross-seller IDOR denied |
| Arbitrary HTML/SVG injection in product descriptions/media | sanitize HTML, media scan, CSP, no dangerous inline scripts | XSS payload inert in preview |
| Admin export reveals PII | export rights, minimization, TTL object, audit of download | low privilege export rejected |
| Slow huge category moves starve DB | jobs/chunking/timeout/quota, async progress | load and cancellation tests |
| Outbox/retry drops approval | worker leases, persisted receipts, reconciliation, alert | process kill before/after commit |
| CSRF on privilege changes | same-site, CSRF double-submit or session-bound token, origin check | cross-origin mutation 403 |
| SSRF through image/metadata URLs | only verified media refs, outbound allowlist | internal URL forbidden |
| Audit altered/deleted | append-only rights + integrity chain/periodic secure export | tamper detection fail release gate |

## Data minimization and logging

Personally identifiable seller/buyer/reporter data accessible only by explicit duty. Mask sensitive fields by default, record read access on sensitive cases. Logs contain request IDs, status, error code, canonical resource UUID, but not bearer tokens, session cookies, evidence document bytes, unrestricted personal addresses or raw payment data. Retention and data subject rights are legal-policy decisions, documented in ADR for actual jurisdiction. Evidence docs scanned and kept encrypted in segregated object storage with signed access and expiry.

## Two-person rules

Policy/role changes and large destructive admin actions require a **proposer** and a distinct **approver**. High privilege cannot self-grant. Changes queue for review with immutable diff, policy_version, TTL and ID-bound approvals. Break-glass emergency procedure uses time-limited activation, MFA, incident ID, follow-up review and tamper-evident audit; no hidden superuser switch.

## Release security gates

Independent role/access matrix (negative tests for all endpoints), OIDC/MFA on real test IdP, SAST/SCA, secret scanning, dependency/containers review, API request fuzzing, CSP check, XSS/CSRF/SSRF/IDOR tests, audit immutability verification, access logs, two-person approval, backup+restore. Critical P0/P1 unresolved → NO-GO.
