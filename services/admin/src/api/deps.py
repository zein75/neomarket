from types import SimpleNamespace
from uuid import UUID

from fastapi import Header, HTTPException, status


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
