from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from redis.exceptions import ConnectionError as RedisConnectionError
from starlette.requests import Request

from src.services.login_rate_limiter import (
    check_login_rate_limit,
    clear_email_login_attempts,
)
from src.main import http_exception_handler


@pytest.mark.asyncio
async def test_login_limiter_uses_hashed_email_and_ip_keys(monkeypatch) -> None:
    monkeypatch.setattr("src.services.login_rate_limiter.settings.login_rate_limit_email_attempts", 8)
    monkeypatch.setattr("src.services.login_rate_limiter.settings.login_rate_limit_ip_attempts", 20)
    redis = AsyncMock()
    redis.eval.return_value = [1, 900]

    await check_login_rate_limit(redis, email=" Seller@example.com ", client_ip="192.0.2.1")

    args = redis.eval.await_args.args
    assert args[1] == 2
    assert args[2].startswith("b2b:login:email:")
    assert args[3].startswith("b2b:login:ip:")
    assert "seller@example.com" not in args[2]
    assert "192.0.2.1" not in args[3]
    assert args[4:] == (900, 8, 20)


@pytest.mark.asyncio
async def test_login_limiter_returns_retry_after_when_limit_is_exceeded() -> None:
    redis = AsyncMock()
    redis.eval.return_value = [0, 317]

    with pytest.raises(HTTPException) as exc_info:
        await check_login_rate_limit(redis, email="seller@example.com", client_ip="192.0.2.1")

    assert exc_info.value.status_code == 429
    assert exc_info.value.headers == {"Retry-After": "317"}


@pytest.mark.asyncio
async def test_login_limiter_fails_closed_when_redis_is_unavailable() -> None:
    redis = AsyncMock()
    redis.eval.side_effect = RedisConnectionError("offline")

    with pytest.raises(HTTPException) as exc_info:
        await check_login_rate_limit(redis, email="seller@example.com", client_ip="192.0.2.1")

    assert exc_info.value.status_code == 503
    assert exc_info.value.headers == {"Retry-After": "1"}


@pytest.mark.asyncio
async def test_successful_login_clears_only_hashed_email_counter() -> None:
    redis = AsyncMock()

    await clear_email_login_attempts(redis, "seller@example.com")

    key = redis.delete.await_args.args[0]
    assert key.startswith("b2b:login:email:")
    assert "seller@example.com" not in key


@pytest.mark.asyncio
async def test_structured_http_exception_preserves_retry_after_header() -> None:
    request = Request({"type": "http", "method": "POST", "path": "/auth/login", "headers": []})
    exc = HTTPException(
        status_code=429,
        detail={"code": "LOGIN_RATE_LIMITED", "message": "Too many login attempts"},
        headers={"Retry-After": "317"},
    )

    response = await http_exception_handler(request, exc)

    assert response.status_code == 429
    assert response.headers["retry-after"] == "317"
