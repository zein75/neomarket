#!/usr/bin/env bash
set -Eeuo pipefail
uv sync --frozen --all-packages
uv run --frozen python ci/create_ci_databases.py
# Keep the migration-only runtime role secret in the process environment for
# every Alembic invocation.  Exporting it avoids shell/runner differences in
# inline assignment handling while keeping the value limited to this ephemeral
# CI job.
export ADMIN_RUNTIME_DB_PASSWORD="ci_admin_runtime_password_only_32_chars"
for service in b2b b2c admin; do
  if [[ "$service" == "admin" ]]; then
    # Isolated CI fixture only; the migration stores this as the login secret
    # for the runtime role created inside the ephemeral PostgreSQL service.
    (cd "services/$service" && DATABASE_URL="postgresql+asyncpg://ci:ci_test_password_only@${PGHOST:-localhost}:5432/$service" uv run --frozen alembic upgrade head)
  else
    (cd "services/$service" && DATABASE_URL="postgresql+asyncpg://ci:ci_test_password_only@${PGHOST:-localhost}:5432/$service" uv run --frozen alembic upgrade head)
  fi
done
PYTHONPATH=services/b2b:shared uv run --frozen pytest -q services/b2b/tests/test_inventory_reservations.py
PYTHONPATH=services/b2c:shared uv run --frozen pytest -q services/b2c/tests/test_postgres_order_concurrency.py
NEOMARKET_ADMIN_POSTGRES_TEST_URL="postgresql+asyncpg://ci:ci_test_password_only@${PGHOST:-localhost}:5432/admin" \
  PYTHONPATH=services/admin:shared uv run --frozen pytest -q \
  services/admin/tests/test_postgres_moderation_claim_concurrency.py \
  services/admin/tests/test_postgres_moderation_decision_races.py \
  services/admin/tests/test_postgres_moderation_queue_keyset.py \
  services/admin/tests/test_postgres_admin_security_audit.py \
  services/admin/tests/test_postgres_operation_retry_idempotency.py \
  services/admin/tests/test_postgres_admin_scope_authorization.py \
  services/admin/tests/test_postgres_moderation_publication_results.py \
  services/admin/tests/test_postgres_moderation_revision_race.py \
  services/admin/tests/test_postgres_operational_metrics.py \
  services/admin/tests/test_postgres_complaint_casework.py \
  services/admin/tests/test_postgres_admin_contract_security.py \
  services/admin/tests/test_postgres_safety_hold.py \
  services/admin/tests/test_postgres_admin_settings.py

# Exercise the latest reversible Admin schema change on the same ephemeral DB
# after all integration tests have completed; CI destroys this service afterward.
(cd services/admin && \
  DATABASE_URL="postgresql+asyncpg://ci:ci_test_password_only@${PGHOST:-localhost}:5432/admin" \
  uv run --frozen alembic downgrade -1 && \
  DATABASE_URL="postgresql+asyncpg://ci:ci_test_password_only@${PGHOST:-localhost}:5432/admin" \
  uv run --frozen alembic upgrade head)
