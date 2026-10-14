# 08 — Production инфраструктура, CI/CD, hardening и безопасный релиз

## OPS-001. Production topology

- **Dev compose никогда не используется как prod.** Отдельные IaC manifests/Helm/managed service config; минимально допустимый надёжный deployment с HA: две API реплики каждой критичной службы в разных failure domains, минимум два worker экземпляра (safe leasing), multi-AZ PostgreSQL primary+replica/failover или managed HA и offsite backup. Если бюджет допускает только один VPS, официальная матрица SLO/DR и single point of failure помечается `NOT MET`, «полный high-availability production» запрещён.
- Gateway/reverse proxy HTTPS (ACME/cert rotation), one explicit internet ingress, no public PostgreSQL/Redis/internal/Admin ports, private service subnet, deny-all+allowlist egress to named dependencies, TLS internally, OIDC SSO private operator access.
- Separate environments staging/prod with distinct secrets/domains, database identity, storage, IAM. Staging copy anonymized; backup read access not granted to CI job unnecessarily.
- DNS, CDN, WAF, persistent connection budget, static assets from object storage, health checks, alert endpoint beyond primary infrastructure. Rate limiting also protects password hashing, expensive catalog, external integrations.

## OPS-002. Container and runtime

- Multi-stage, lockfile `uv sync --frozen`, final nonroot UID/GID, drop capabilities, `no-new-privileges`, read-only root FS with explicitly writable tmp if needed, seccomp baseline, resource requests/limits, pids, restart policy, graceful shutdown/drain, predictable startup.
- Pin base image by digest not `:latest`, vulnerability scan in CI, verify signed provenance or trusted registry, generate SBOM, maintain dependency update program; run `uv lock --check` or reproducible install. No cleartext secret embedded in image/layer or public Compose.
- No migrations at API container start. One-shot migration job with exclusive lock, rollback plan, preflight report and maintenance coordination.
- Worker separates tasks from HTTP (no background tasks per FastAPI lifespan); each job claims `SKIP LOCKED` lease and uses fencing/version to prevent stale acknowledgments.
- `/live`: process heartbeat only, no DB dependency. `/ready`: DB ping, pool, critical schema readiness, worker service SLI measured separately; do not require Admin for B2B read API readiness when not critical. Health routes must not reveal schema details/credentials publicly.

## OPS-003. CI gates before merge

1. Ruff/formatter/check type system (`mypy` or `pyright`), import compile, `uv lock --check`, security lint.
2. Full unit tests by service (all discovered, no selective -k substitution), coverage gate on critical paths e.g. >=90% branches on inventory/order/moderation business transitions **plus** mandatory tests (coverage alone insufficient).
3. Real DB integration with PostgreSQL service containers and isolated schemas, migration smoke, concurrency and timeouts; contract tests against current `contracts/*.openapi.yaml`/JSON Schema, producer/consumer samples.
4. SAST/secret scan, dependency vulnerability scan (severity policy: no exploitable Critical/High without signed time-bounded exception), container scanner, IaC scanner, license audit/SBOM. Require review of new critical dependency/security baseline.
5. E2E flow and short load smoke on staging, no production secret use in PR builds; only trusted branches can release.
6. Signed reproducible artifacts: manifest with git SHA, tested build digest, contract revision/hash and migration heads. Two-person review for migrations, auth, payments and role policy.

## OPS-004. Deploy and rollback

- Immutable image build -> staging -> smoke/integration/fault subset -> sign-off -> canary 1%/5%/25%/100% traffic with observation windows and explicit auto rollback thresholds (5xx, p95/p99, queue lag, integrity alerts).
- Run compatible `expand` migration before releasing new code. Workers canary separately; confirm old/new event schema compatibility; disable legacy inv write endpoints before switching.
- Deploy failure rolls back **code** only when DB backward compatible; otherwise stop writes and use forward fix with incident commander approval, not undocumented downgrade.
- Full audit of release, audit event for manual interventions, incident on rollback, frozen write feature flag for order/stock actions, healthy fail-open only for public read endpoints when explicitly safe.

## OPS-005. Capacity/performance

- Workload characterization: number sellers/products/SKUs/orders/cart operations, search/filter mix, concurrent checkout, peak burst, external service latency. Define baseline numeric requests/sec in release config (`capacity-profile.yaml`) before perf tests.
- Catalog: move filtering/sorting/pagination to indexed SQL, EXPLAIN ANALYZE, optional PostgreSQL FTS/search index; never `.all()` then Python filtering on unbounded catalog. Query limits, sort allowlist, max page=100, safe indexes, prepared SQL.
- Connection pools across N API replicas+workers satisfy capacity formula `Σ(max_connections app pools) + maintenance_headroom < DB max_connections`. Side-effects bounded by worker concurrency, rate limits and downstream timeouts.
- Graceful degrade via 429/503 with retry and `202 PENDING` only for persisted operation; circuit breaker cannot synthesize success.
- Load test >=2x forecasted peak, >=3x expected dataset, at least 24h soak, injected slowness and disk/WAL pressure; establish p95/p99 measured profiles before GO.

## OPS-006. Secrets, filesystem, network proof

- Build smoke rejects `postgres/postgres`, known dev secrets, missing auth public keys, `DEBUG=true` in prod; processes fail-fast.
- External port scan verifies only 443 (and controlled management) exposed. Admin requires VPN/IP allowlist+SSO MFA; private service origins inaccessible from public internet.
- Encrypted transport, DB schema permissions, no root container; secrets rotation tested before release, emergency revoke known documented.

## OPS-007. CI artifact requirements

A PR cannot merge without status pass; every rollout records `ci_run_id`, `image_digest`, `alembic_version`, `contract_hash`, `rollback_manifest`, canary dashboards, operator sign-off. Security/IaC exception has owner, severity, exploitability, expiry and compensating control; P0/P1 business correctness cannot be waived for full release.
