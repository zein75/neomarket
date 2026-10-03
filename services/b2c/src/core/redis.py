import redis.asyncio as aioredis

from .config import settings

_pool = aioredis.ConnectionPool.from_url(settings.redis_url, decode_responses=True)


def get_redis() -> aioredis.Redis:
    return aioredis.Redis(connection_pool=_pool)
