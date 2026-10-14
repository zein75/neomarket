# Build context: repo root (docker compose context: .)
FROM python:3.12-slim@sha256:2b4f19dae3a777dfc3b76730bda1e82e1f66ab2a2686fa93ca78edbfb4f04ffe

# Install uv
COPY --from=ghcr.io/astral-sh/uv:0.11.28@sha256:5c3ab83183a73c5d319a77009eb425b60d5bb937f339fb7876788ebf567baf48 /uv /usr/local/bin/uv

WORKDIR /app

# Docker Desktop's NAT can stall uv's default 50 parallel downloads.
ENV UV_CONCURRENT_DOWNLOADS=4

# Copy workspace-level files needed for dependency resolution
COPY pyproject.toml uv.lock ./

# Copy workspace members required by b2c
COPY shared/ ./shared/
COPY services/b2c/ ./services/b2c/

# Install b2c and all its dependencies (skip dev deps)
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --package b2c

RUN useradd --create-home --uid 10001 app \
    && chown -R app:app /app
USER app
ENV UV_CACHE_DIR=/home/app/.cache/uv

WORKDIR /app/services/b2c

EXPOSE 8001

# Migrations run in the dedicated one-shot compose job.
CMD ["uv", "run", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8001"]
