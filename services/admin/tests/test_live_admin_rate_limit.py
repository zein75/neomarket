import os
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport
from redis.asyncio import Redis

from src.api.middleware import AdminRequestLimitsMiddleware
from src.core.config import settings
from src.services import rate_limiter


@pytest.mark.asyncio
async def test_live_admin_rate_limit_returns_problem_429_with_retry_after() -> None:
    redis_url = os.getenv("NEOMARKET_ADMIN_RATE_LIMIT_REDIS_URL")
    if not redis_url:
        pytest.skip("set NEOMARKET_ADMIN_RATE_LIMIT_REDIS_URL to a disposable Redis")

    route = f"/admin/v1/rate-limit-probe-{uuid4().hex}"
    app = FastAPI()

    @app.get(route)
    async def probe() -> dict[str, bool]:
        return {"ok": True}

    app.add_middleware(AdminRequestLimitsMiddleware)
    previous = (settings.redis_url, settings.admin_rate_limit_requests, settings.admin_rate_limit_window_seconds, settings.app_env, settings.admin_allow_dev_auth)
    settings.redis_url = redis_url
    settings.admin_rate_limit_requests = 1
    settings.admin_rate_limit_window_seconds = 30
    settings.app_env = "production"
    settings.admin_allow_dev_auth = False
    rate_limiter._redis = None
    redis = Redis.from_url(redis_url, decode_responses=False)
    try:
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            first = await client.get(route)
            second = await client.get(route)
        assert first.status_code == 200, first.text
        assert second.status_code == 429, second.text
        assert second.headers.get("Retry-After")
        assert second.headers["content-type"].startswith("application/problem+json")
        assert second.json()["code"] == "RATE_LIMITED"
    finally:
        key_prefix = "admin:rate:"
        keys = [key async for key in redis.scan_iter(match=f"{key_prefix}*")]
        if keys:
            await redis.delete(*keys)
        await redis.aclose()
        if rate_limiter._redis is not None:
            await rate_limiter._redis.aclose()
        rate_limiter._redis = None
        settings.redis_url, settings.admin_rate_limit_requests, settings.admin_rate_limit_window_seconds, settings.app_env, settings.admin_allow_dev_auth = previous
