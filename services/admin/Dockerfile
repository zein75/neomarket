# Build context: repo root
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Docker Desktop's NAT can stall uv's default 50 parallel downloads.
ENV UV_CONCURRENT_DOWNLOADS=4

COPY pyproject.toml uv.lock ./
COPY shared/ ./shared/
COPY services/admin/ ./services/admin/

RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --package admin

WORKDIR /app/services/admin

EXPOSE 8003

CMD ["sh", "-c", "uv run alembic upgrade head && uv run uvicorn src.main:app --host 0.0.0.0 --port 8003"]
