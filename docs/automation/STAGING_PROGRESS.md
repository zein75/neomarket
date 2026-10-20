# Staging progress

**Updated:** 2026-10-20 11:10 Asia/Yekaterinburg

| Phase | Status | Evidence |
|---|---|---|
| S0 host audit | DONE | `STAGING_INFRA_AUDIT.md` and captured server audit |
| S1 restricted deployment | DONE | fixed-SHA wrapper, forced SSH command, root-only Docker credentials |
| S2 filesystem/secrets | DONE | root-owned `/etc/neomarket/staging.env`, persistent volumes, no secret values in Git |
| S3 Compose runtime | PASS | deployment `7c195105…` completed; all core services and gateway healthy |
| S4 ingress/HTTPS | PARTIAL | Caddy internal TLS and four virtual hosts work; CA/browser trust not yet installed |
| S5 migrations/integration | PASS for startup | B2B, B2C and Admin migrations completed; PostgreSQL/Redis healthy |
| S6 Keycloak/OIDC/MFA | PARTIAL | Keycloak realm imported and healthy; real browser OIDC/MFA evidence not run |
| S7 media/antivirus | PASS for startup | ClamAV healthy and B2B depends on it; full upload/quarantine evidence not run |
| S8 workers/events | PASS for startup | taxonomy/recovery/admin workers running; retry/DLQ scenario evidence not run |
| S9 CI/CD | PASS for verified image build | CI image build and protected wrapper deployment succeeded |
| S10 browser QA | BLOCKED | Caddy CA is untrusted in the current browser environment; no authenticated manifests |
| S13 backup/restore | NOT RUN | external backup target and restore drill are not configured |
| S14 security audit | PARTIAL | static Compose gates and ingress smoke passed; full runtime audit remains |

**Current release status: BLOCKED.** Production readiness is not asserted while browser, backup/restore, authenticated QA, visual, and full security evidence are missing.
