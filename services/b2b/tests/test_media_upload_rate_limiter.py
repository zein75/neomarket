from uuid import uuid4

import pytest
from fastapi import HTTPException
from redis.exceptions import RedisError

from src.core.config import settings
from src.services.media_upload_rate_limiter import check_media_upload_rate_limit


class FakeRedis:
    def __init__(self, result=(1, 3600), error: Exception | None = None):
        self.result = result
        self.error = error
        self.calls: list[tuple] = []

    async def eval(self, *args):
        self.calls.append(args)
        if self.error:
            raise self.error
        return self.result


@pytest.mark.asyncio
async def test_media_upload_rate_limit_is_seller_scoped(monkeypatch):
    monkeypatch.setattr(settings, "media_upload_rate_limit_requests", 30)
    monkeypatch.setattr(settings, "media_upload_rate_limit_window_seconds", 3600)
    redis = FakeRedis()
    seller_id = uuid4()

    await check_media_upload_rate_limit(redis, seller_id)

    assert len(redis.calls) == 1
    assert redis.calls[0][1] == 1
    assert redis.calls[0][2].startswith("b2b:media-upload:seller:")
    assert str(seller_id) not in redis.calls[0][2]
    assert redis.calls[0][3:] == (3600, 30)


@pytest.mark.asyncio
async def test_media_upload_rate_limit_returns_retry_after(monkeypatch):
    monkeypatch.setattr(settings, "media_upload_rate_limit_requests", 1)
    redis = FakeRedis(result=(0, 42))

    with pytest.raises(HTTPException) as caught:
        await check_media_upload_rate_limit(redis, uuid4())

    assert caught.value.status_code == 429
    assert caught.value.headers["Retry-After"] == "42"
    assert caught.value.detail["code"] == "MEDIA_UPLOAD_RATE_LIMITED"


@pytest.mark.asyncio
async def test_media_upload_rate_limit_fails_closed_when_redis_is_unavailable():
    redis = FakeRedis(error=RedisError("down"))

    with pytest.raises(HTTPException) as caught:
        await check_media_upload_rate_limit(redis, uuid4())

    assert caught.value.status_code == 503
    assert caught.value.detail["code"] == "MEDIA_UPLOAD_PROTECTION_UNAVAILABLE"
