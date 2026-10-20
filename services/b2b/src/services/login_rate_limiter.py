import hashlib
import hmac

from fastapi import HTTPException, status
from redis.asyncio import Redis
from redis.exceptions import RedisError

from src.core.config import settings

_INCREMENT_IF_ALLOWED = """
local email_count = redis.call('INCR', KEYS[1])
if email_count == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
local ip_count = redis.call('INCR', KEYS[2])
if ip_count == 1 then redis.call('EXPIRE', KEYS[2], ARGV[1]) end
local email_ttl = redis.call('TTL', KEYS[1])
local ip_ttl = redis.call('TTL', KEYS[2])
local ttl = math.max(email_ttl, ip_ttl)
if email_count > tonumber(ARGV[2]) or ip_count > tonumber(ARGV[3]) then
  return {0, ttl}
end
return {1, ttl}
"""


def _digest(value: str) -> str:
    return hmac.new(
        settings.secret_key.encode(), value.encode(), hashlib.sha256
    ).hexdigest()


async def check_login_rate_limit(
    redis: Redis, *, email: str, client_ip: str, action: str = "login"
) -> None:
    if action not in {"login", "register", "invite"}:
        raise ValueError("Unsupported authentication rate-limit action")
    email_key = f"b2b:{action}:email:{_digest(email.strip().casefold())}"
    ip_key = f"b2b:{action}:ip:{_digest(client_ip)}"
    try:
        allowed, ttl = await redis.eval(
            _INCREMENT_IF_ALLOWED,
            2,
            email_key,
            ip_key,
            settings.login_rate_limit_window_seconds,
            settings.login_rate_limit_email_attempts,
            settings.login_rate_limit_ip_attempts,
        )
    except RedisError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "LOGIN_PROTECTION_UNAVAILABLE", "message": "Login temporarily unavailable"},
            headers={"Retry-After": "1"},
        ) from exc

    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"code": "LOGIN_RATE_LIMITED", "message": "Too many login attempts"},
            headers={"Retry-After": str(max(1, ttl))},
        )


async def clear_email_login_attempts(redis: Redis, email: str) -> None:
    key = f"b2b:login:email:{_digest(email.strip().casefold())}"
    try:
        await redis.delete(key)
    except RedisError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "LOGIN_PROTECTION_UNAVAILABLE", "message": "Login temporarily unavailable"},
            headers={"Retry-After": "1"},
        ) from exc
