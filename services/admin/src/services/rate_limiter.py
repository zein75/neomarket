import hashlib

from fastapi import HTTPException, status
from redis.asyncio import Redis
from redis.exceptions import RedisError

from src.core.config import settings


_INCREMENT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
local ttl = redis.call('TTL', KEYS[1])
if count > tonumber(ARGV[2]) then return {0, ttl} end
return {1, ttl}
"""


_redis: Redis | None = None


def _client() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(settings.redis_url, decode_responses=False)
    return _redis


async def enforce_admin_rate_limit(*, client_ip: str, route: str) -> int | None:
    key = "admin:rate:" + hashlib.sha256(f"{client_ip}:{route}".encode()).hexdigest()
    try:
        allowed, ttl = await _client().eval(
            _INCREMENT,
            1,
            key,
            settings.admin_rate_limit_window_seconds,
            settings.admin_rate_limit_requests,
        )
    except RedisError as exc:
        if settings.local_dev_auth_enabled:
            return None
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "RATE_LIMIT_PROTECTION_UNAVAILABLE", "message": "Request protection is temporarily unavailable"},
            headers={"Retry-After": "1"},
        ) from exc
    retry_after = max(1, int(ttl or settings.admin_rate_limit_window_seconds))
    if int(allowed) != 1:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"code": "RATE_LIMITED", "message": "Request rate limit exceeded"},
            headers={"Retry-After": str(retry_after)},
        )
    return retry_after
