from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db, verify_service_key
from src.schemas.moderation_event import ModerationDecisionEvent
from src.services.moderation_event_service import ModerationEventService

router = APIRouter(tags=["moderation-events"])


@router.post("/api/v1/events/moderation", status_code=status.HTTP_204_NO_CONTENT)
async def apply_moderation_event(
    event: ModerationDecisionEvent,
    _: None = Depends(verify_service_key),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await ModerationEventService(db).apply(event)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/api/v1/moderation/events", status_code=status.HTTP_204_NO_CONTENT)
async def apply_moderation_event_alias(
    event: ModerationDecisionEvent,
    _: None = Depends(verify_service_key),
    db: AsyncSession = Depends(get_db),
) -> Response:
    return await apply_moderation_event(event, _, db)
