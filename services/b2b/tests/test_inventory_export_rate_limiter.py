from uuid import uuid4

import pytest
from fastapi import HTTPException
from redis.exceptions import RedisError

from src.services.inventory_export_rate_limiter import check_inventory_export_rate_limit


class RedisStub:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.args = None

    async def eval(self, *args):
        self.args = args
        if self.error:
            raise self.error
        return self.result


@pytest.mark.asyncio
async def test_inventory_export_rate_limit_uses_seller_scoped_key():
    redis = RedisStub(result=[1, 3600])

    await check_inventory_export_rate_limit(redis, uuid4())

    assert redis.args[1] == 1
    assert redis.args[2].startswith("b2b:inventory-export:seller:")


@pytest.mark.asyncio
async def test_inventory_export_rate_limit_returns_retry_after_when_exceeded():
    redis = RedisStub(result=[0, 123])

    with pytest.raises(HTTPException) as raised:
        await check_inventory_export_rate_limit(redis, uuid4())

    assert raised.value.status_code == 429
    assert raised.value.headers["Retry-After"] == "123"


@pytest.mark.asyncio
async def test_inventory_export_rate_limit_fails_closed_when_redis_unavailable():
    redis = RedisStub(error=RedisError("unavailable"))

    with pytest.raises(HTTPException) as raised:
        await check_inventory_export_rate_limit(redis, uuid4())

    assert raised.value.status_code == 503
    assert raised.value.detail["code"] == "EXPORT_PROTECTION_UNAVAILABLE"
