from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis

from src.core.database import get_db
from src.core.config import settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> dict:
    return {"status": "ok"}




@router.get("/live")
async def liveness() -> dict:
    return {"status": "ok"}


@router.get("/ready")
async def readiness(db: AsyncSession = Depends(get_db)) -> dict:
    try:
        await db.execute(text("SELECT 1"))
        redis = Redis.from_url(settings.redis_url)
        try:
            await redis.ping()
        finally:
            await redis.aclose()
    except Exception as exc:  # noqa: BLE001 - readiness must fail closed
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "NOT_READY", "message": "Database unavailable"},
        ) from exc
    return {"status": "ok"}
