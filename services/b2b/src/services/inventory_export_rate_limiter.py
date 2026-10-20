import hashlib
import hmac
from uuid import UUID

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


async def check_inventory_export_rate_limit(redis: Redis, seller_id: UUID) -> None:
    seller_digest = hmac.new(
        settings.secret_key.encode(), str(seller_id).encode(), hashlib.sha256
    ).hexdigest()
    try:
        allowed, ttl = await redis.eval(
            _INCREMENT,
            1,
            f"b2b:inventory-export:seller:{seller_digest}",
            settings.inventory_export_rate_limit_window_seconds,
            settings.inventory_export_rate_limit_requests,
        )
    except RedisError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "EXPORT_PROTECTION_UNAVAILABLE", "message": "Inventory export temporarily unavailable"},
            headers={"Retry-After": "1"},
        ) from exc

    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"code": "INVENTORY_EXPORT_RATE_LIMITED", "message": "Too many inventory export requests"},
            headers={"Retry-After": str(max(1, ttl))},
        )
