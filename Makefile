.DEFAULT_GOAL := help
.PHONY: help up down restart logs ps build prod sync \
        b2c-run b2c-migrate b2c-revision b2c-downgrade b2c-history \
        b2b-run b2b-migrate b2b-revision b2b-downgrade b2b-history \
        admin-run admin-migrate admin-revision admin-downgrade admin-history \
        admin-test b2b-test \
        lint lint-fix format test test-all verify lock-check


up:
	docker compose up -d

down:
	docker compose down

restart:
	docker compose restart

logs:
	docker compose logs -f

ps:
	docker compose ps

build:
	docker compose build

prod:
	docker compose --env-file /etc/neomarket/production.env -f docker-compose.prod.yaml up -d


b2c-run:
	cd services/b2c && uv run uvicorn src.main:app --reload --port 8001

b2c-migrate:
	cd services/b2c && uv run alembic upgrade head

b2c-revision:
	cd services/b2c && uv run alembic revision --autogenerate -m "$(name)"

b2c-downgrade:
	cd services/b2c && uv run alembic downgrade -1

b2c-history:
	cd services/b2c && uv run alembic history --verbose


b2b-run:
	cd services/b2b && uv run uvicorn src.main:app --reload --port 8002

b2b-migrate:
	cd services/b2b && uv run alembic upgrade head

b2b-revision:
	cd services/b2b && uv run alembic revision --autogenerate -m "$(name)"

b2b-downgrade:
	cd services/b2b && uv run alembic downgrade -1

b2b-history:
	cd services/b2b && uv run alembic history --verbose


admin-run:
	cd services/admin && uv run uvicorn src.main:app --reload --port 8003

admin-migrate:
	cd services/admin && uv run alembic upgrade head

admin-revision:
	cd services/admin && uv run alembic revision --autogenerate -m "$(name)"

admin-downgrade:
	cd services/admin && uv run alembic downgrade -1

admin-history:
	cd services/admin && uv run alembic history --verbose


lint:
	uv run ruff check shared/shared services/b2b/src services/b2c/src services/admin/src

lint-fix:
	uv run ruff check shared/shared services/b2b/src services/b2c/src services/admin/src --fix

format:
	uv run ruff format shared/shared services/b2b/src services/b2c/src services/admin/src


test:            ## Run b2c tests
	cd services/b2c && uv run pytest tests/ -v

test-all:        ## Run every service and shared test suite
	PYTHONPATH=services/b2c:shared uv run pytest -q services/b2c/tests
	PYTHONPATH=services/b2b:shared uv run pytest -q services/b2b/tests
	PYTHONPATH=services/admin:shared uv run pytest -q services/admin/tests
	PYTHONPATH=shared uv run pytest -q shared/tests tests

lock-check:      ## Verify reproducible dependency lock
	uv lock --check

verify:          ## Run release verification gates
	uv lock --check
	uv run ruff check shared/shared services/b2b/src services/b2c/src services/admin/src
	uv run python docs/NEOMARKET_PRODUCTION_SPEC_V2_2026-10-14/qa/validate_spec.py
	uv run python scripts/check_openapi_routes.py
	$(MAKE) test-all

admin-test:
	cd services/admin && uv run pytest tests/ -v

b2b-test:
	cd services/b2b && uv run pytest tests/ -v



sync:
	uv sync --all-packages


help:
	@grep -E '^[a-zA-Z_-]+:.*##' Makefile | \
		awk 'BEGIN {FS = ":.*##"}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
