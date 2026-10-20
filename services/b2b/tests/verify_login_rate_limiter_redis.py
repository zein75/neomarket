from __future__ import annotations

import asyncio
from uuid import uuid4

from fastapi import HTTPException
from redis.asyncio import Redis

from src.core.config import settings
from src.services.login_rate_limiter import _digest, check_login_rate_limit


async def verify_login_rate_limiter(redis: Redis) -> None:
    run_id = uuid4().hex
    email = f"seller-{run_id}@example.test"
    email_ips = [
        f"198.51.100.{index}"
        for index in range(1, settings.login_rate_limit_email_attempts + 2)
    ]
    ip = f"192.0.2.{int(run_id[:2], 16) % 253 + 1}"
    ip_emails = [
        f"attempt-{index}-{run_id}@example.test"
        for index in range(settings.login_rate_limit_ip_attempts + 1)
    ]
    keys = {
        f"b2b:login:email:{_digest(email)}",
        *(f"b2b:login:ip:{_digest(value)}" for value in email_ips),
        *(f"b2b:login:email:{_digest(value)}" for value in ip_emails),
        f"b2b:login:ip:{_digest(ip)}",
    }

    try:
        await redis.delete(*keys)
        for client_ip in email_ips[:-1]:
            await check_login_rate_limit(redis, email=email, client_ip=client_ip)
        try:
            await check_login_rate_limit(redis, email=email, client_ip=email_ips[-1])
        except HTTPException as exc:
            assert exc.status_code == 429
            assert int(exc.headers["Retry-After"]) > 0
        else:
            raise AssertionError("email attempt limit was not enforced")

        for attempt_email in ip_emails[:-1]:
            await check_login_rate_limit(redis, email=attempt_email, client_ip=ip)
        try:
            await check_login_rate_limit(redis, email=ip_emails[-1], client_ip=ip)
        except HTTPException as exc:
            assert exc.status_code == 429
            assert int(exc.headers["Retry-After"]) > 0
        else:
            raise AssertionError("IP attempt limit was not enforced")
    finally:
        await redis.delete(*keys)


async def main() -> None:
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        await verify_login_rate_limiter(redis)
        print(
            "PASS: Redis Lua enforced email threshold="
            f"{settings.login_rate_limit_email_attempts} and IP threshold="
            f"{settings.login_rate_limit_ip_attempts}; Retry-After returned; "
            "scoped counters cleaned."
        )
    finally:
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
