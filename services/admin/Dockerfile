# Build context: repo root
FROM python:3.12-slim@sha256:2b4f19dae3a777dfc3b76730bda1e82e1f66ab2a2686fa93ca78edbfb4f04ffe

COPY --from=ghcr.io/astral-sh/uv:0.11.28@sha256:5c3ab83183a73c5d319a77009eb425b60d5bb937f339fb7876788ebf567baf48 /uv /usr/local/bin/uv

WORKDIR /app

# Docker Desktop's NAT can stall uv's default 50 parallel downloads.
ENV UV_CONCURRENT_DOWNLOADS=4

COPY pyproject.toml uv.lock ./
COPY shared/ ./shared/
COPY services/admin/ ./services/admin/

RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --package admin

RUN useradd --create-home --uid 10001 app \
    && chown -R app:app /app
USER app
ENV UV_CACHE_DIR=/home/app/.cache/uv

WORKDIR /app/services/admin

EXPOSE 8003

# Migrations run in the dedicated one-shot compose job.
CMD ["uv", "run", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8003"]
