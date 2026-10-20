# Open architecture/business decisions — must be approved, not guessed

| ADR | Decision required | Default safe implementation pending decision |
|---|---|---|
| ADR-ADMIN-01 | Real OIDC provider, MFA and step-up claims | Fail closed Admin auth; no local fallback |
| ADR-ADMIN-02 | Staff roles/scopes/org/regional separation | Least privilege; no publish/hard-block until role mapping signed off |
| ADR-ADMIN-03 | Exact moderation reason taxonomy and prohibited-listing policy | Require explicit reason; no automated hard block on heuristic alone |
| ADR-ADMIN-04 | Allowed status actions of an already published product being edited | Keep prior valid revision if safe, new revision pending; safety hold separate |
| ADR-ADMIN-05 | Slug uniqueness and public URL canonicalization across taxonomy | Prevent duplicate paths, hold move until redirect policy approved |
| ADR-ADMIN-06 | Category inheritance/override and grandfathered old products | Schema changes apply to new submissions; old products flagged for migration review |
| ADR-ADMIN-07 | Scope of seller compliance (country, documents, business onboarding) | No fake KYC verification; mark BLOCKED |
| ADR-ADMIN-08 | Appeal deadlines and independence requirements | Reviewer cannot be original decision actor; configurable policy |
| ADR-ADMIN-09 | Temporary safety hold expiry and irreversible block requirements | Short bounded hold, audit and escalation, no silent termination |
| ADR-ADMIN-10 | PII/evidence/log data retention and staff audit access | Data minimization + secure storage; legal signoff pending |
| ADR-ADMIN-11 | Threshold for two-person approval on bulk operations | Require approval for all high-impact writes until threshold approved |
| ADR-ADMIN-12 | Model of brand verification and duplicate product/offer grouping | No automatic irreversible merge |
| ADR-ADMIN-13 | Expected RPO/RTO/SLO, alerting thresholds and release capacity | Design monitoring, leave production readiness BLOCKED until measured |
| ADR-ADMIN-14 | Financial, refund, tax, logistics admin functions and jurisdiction | Read-only scoped views, no payment mutations until provider/policy agreed |

For each ADR record owner, date, considered alternatives, decision, consequences, schemas/tests affected and acceptance by responsible stakeholders. New components absent from Stitch need approved visual extension; do not invent and call it pixel-perfect to a nonexistent screen.
