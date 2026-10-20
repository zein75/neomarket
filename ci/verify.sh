#!/usr/bin/env bash
set -Eeuo pipefail
uv sync --frozen --all-packages
uv lock --check
uv run --frozen ruff check shared/shared services/b2b/src services/b2c/src services/admin/src
uv run --frozen python ci/validate_current_admin_spec.py
uv run --frozen python scripts/check_openapi_routes.py
uv run --frozen python ci/check_staging_config.py
PYTHONPATH=services/b2b:shared uv run --frozen pytest -q services/b2b/tests
PYTHONPATH=services/b2c:shared uv run --frozen pytest -q services/b2c/tests
PYTHONPATH=services/admin:shared uv run --frozen pytest -q services/admin/tests
PYTHONPATH=shared uv run --frozen pytest -q shared/tests tests
