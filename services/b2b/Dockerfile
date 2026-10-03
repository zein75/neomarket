# Build context: repo root (docker compose context: .)
FROM python:3.12-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Docker Desktop's NAT can stall uv's default 50 parallel downloads.
ENV UV_CONCURRENT_DOWNLOADS=4

# Copy workspace-level files needed for dependency resolution
COPY pyproject.toml uv.lock ./

# Copy workspace members required by b2b
COPY shared/ ./shared/
COPY services/b2b/ ./services/b2b/

# Install b2b and all its dependencies (skip dev deps)
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --package b2b

WORKDIR /app/services/b2b

EXPOSE 8002

# Run migrations then start the server
CMD ["sh", "-c", "uv run alembic upgrade head && uv run uvicorn src.main:app --host 0.0.0.0 --port 8002"]
