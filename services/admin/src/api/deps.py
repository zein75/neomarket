from types import SimpleNamespace
from uuid import UUID

from fastapi import Header, HTTPException, status

from src.core.config import settings


async def get_current_moderator(
    x_moderator_id: str | None = Header(default=None, alias="X-Moderator-Id"),
) -> SimpleNamespace:
    if not x_moderator_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing moderator identity",
        )
    try:
        moderator_id = UUID(x_moderator_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid moderator identity",
        )
    return SimpleNamespace(id=moderator_id)


async def verify_service_key(
    x_service_key: str | None = Header(default=None, alias="X-Service-Key"),
) -> None:
    if x_service_key != settings.service_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "message": "Invalid service key"},
        )
