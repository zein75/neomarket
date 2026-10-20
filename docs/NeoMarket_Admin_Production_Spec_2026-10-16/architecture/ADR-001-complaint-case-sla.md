# ADR-001: Complaint case operational SLA

- Status: accepted for the initial Admin implementation; review with the policy owner before production rollout.
- Date: 2026-10-16.

## Decision

New complaint cases receive a persisted `deadline_at`, computed once at intake from `COMPLAINT_CASE_SLA_SECONDS`. The default is 86,400 seconds (24 hours); deployments can set a different positive duration. The deadline is an operational workflow target only. It does not represent a jurisdiction-specific legal deadline or pause automatically when a case is escalated.

Existing complaints retain a null deadline because their original policy cannot be reconstructed safely. Changing the configured duration affects new cases only.

## Consequences

Admin detail and queue responses can show the recorded due time, and the status/deadline index supports overdue-case queries. Legal deadlines, pause rules, and notification delivery require policy-owner decisions and a verified notice integration; this ADR does not define them.
