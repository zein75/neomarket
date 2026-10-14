#!/usr/bin/env bash
set -Eeuo pipefail
uv sync --frozen --all-packages
uv run --frozen python ci/create_ci_databases.py
for service in b2b b2c admin; do
  (cd "services/$service" && DATABASE_URL="postgresql+asyncpg://ci:ci_test_password_only@${PGHOST:-localhost}:5432/$service" uv run --frozen alembic upgrade head)
done
PYTHONPATH=services/b2b:shared uv run --frozen pytest -q services/b2b/tests/test_inventory_reservations.py
PYTHONPATH=services/b2c:shared uv run --frozen pytest -q services/b2c/tests/test_postgres_order_concurrency.py
