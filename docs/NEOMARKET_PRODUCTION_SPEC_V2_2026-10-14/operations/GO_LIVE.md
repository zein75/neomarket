# Production GO / NO-GO protocol

**Policy:** Всегда NO-GO при любом незакрытом P0/P1, недоказанной сохранности заказов/денег, проваленном DR test, публичной неавторизованной модификации, неконтролируемом stock mismatch, отсутствии critical alert или обязательном для бизнеса платеже без проверенного PSP. Для «полного production» P2 закрываются, а узкая business scope оформляется документально.

## Подписи/инфраструктура

- [ ] Назначены product owner, tech lead, security owner, SRE/on-call, DBA, incident commander и backup delegate; контактные каналы реально протестированы.
- [ ] Все O-01..O-12 из planning/DECISIONS.md одобрены либо документирована явно урезанная область запуска, пользователи не вводятся в заблуждение.
- [ ] Зафиксированы commit SHA, image digests, contract hash, DB migration heads, list of feature flags и rollback manifest.
- [ ] Public ingress только TLS gateway, Admin private/SSO MFA, DB/Redis/internal routes из интернета недоступны; external scan evidence.
- [ ] Secrets random, independently scoped, stored/rotated in vault, no defaults, no source leaks. Network role and DB privilege checks PASS.

## Correctness and functionality

- [ ] Product CRUD -> moderation ticket -> claim+decision -> B2B -> B2C visibility E2E PASS and revision conflict handling.
- [ ] Checkout/cancel/fulfill E2E and compensations PASS with 2+ workers, DB loss, network timeouts, ACK loss; 0 orphan / 0 double effect.
- [ ] `reserved_quantity = SUM(active lines)` everywhere, no negative price/on_hand, no seller update below reserved.
- [ ] Reject forged moderator/owner/service identities, negative body, hidden legacy inventory endpoints removed.
- [ ] Consumer/producer JSON Schema and live OpenAPI vs contracts diff 0; new API version exclusive authority.
- [ ] All enabled endpoints implement RBAC, bounded pagination, stable error envelope and idempotency semantics.
- [ ] Payment/delivery/refund/settlement mode explicitly approved; no fake `PAID`, `DELIVERED`.

## Quality and operational readiness

- [ ] Full all-service pytest/integration/contract/fault suites green, no skipped release-critical tests; reports attached.
- [ ] 2x peak load / 3x data volume / 24h soak meet agreed p95/p99/error budgets; no OOM, deadlocks, queue accumulation.
- [ ] No unaccepted Critical/High SAST/DAST/container/dependency findings, manual security testing documented.
- [ ] Schema upgrade on current-like snapshot PASS, migration preflight/backfill and rollback compatibility PASS; separate one-shot job.
- [ ] Outbox/inbox retries, DLQ, reconciliation and protected manual replay verified; actual alert received by on-call.
- [ ] Offsite encrypted immutable PITR backup OK; clean-room restore **performed**, cross-DB reconciliation and measured RPO/RTO within target, last drill recent.
- [ ] Logs/traces/metrics/audit/alerts active; secrets/PII redaction and security event monitoring PASS.
- [ ] Incident, DR and backup runbooks reviewed; rollback and canary abort test PASS; support escalation staffed.

## Canary protocol and stop conditions

1. Freeze schema contract and flags, snapshot/backup verified. Canary 1% for measured observation, then 5%, 25%, 100% according to risk/traffic profile; worker rollout separately.
2. Monitor: DB errors, 5xx, p95/p99, outbox oldest age, checkout pending, cancellations, fulfillments, moderation backlog, stock reconciler, backup WAL, security denies.
3. **Immediate stop/freeze affected writes** on any confirmed inventory invariant violation, unauthorized write, data mismatch with actual impact, missing backup coverage, duplicated payment/fulfillment or poison events not recoverable. Preserve events; initiate incident not silent retries.
4. Auto rollback code if schema compatible; otherwise maintain safe read-only and apply reviewed forward-fix/restore procedure. After recovery sign checklist again.

## GO decision record (fill before release)

```text
Release ID: ___________________
Git SHA / image digests: _______
OpenAPI contract hashes: ______
DB migration heads: ___________
Security report / date: _______
Load/soak report / date: ______
Fault-test report / date: _____
DR restore report / actual RPO/RTO: ______
Unclosed P0/P1/P2: ____________
Business scope / PSP / logistics: ________
Tech lead: ______ Security: ______ SRE: ______ Product: ______
Decision: GO / NO-GO, timestamp: _______
```
