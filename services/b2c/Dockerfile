# Build context: repo root (docker compose context: .)
FROM python:3.12-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy workspace-level files needed for dependency resolution
COPY pyproject.toml uv.lock ./

# Copy workspace members required by b2c
COPY shared/ ./shared/
COPY services/b2c/ ./services/b2c/

# Install b2c and all its dependencies (skip dev deps)
RUN uv sync --frozen --no-dev --package b2c

WORKDIR /app/services/b2c

EXPOSE 8001

# Run migrations then start the server
CMD ["sh", "-c", "uv run alembic upgrade head && uv run uvicorn src.main:app --host 0.0.0.0 --port 8001"]
