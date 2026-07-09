from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db, verify_service_key
from src.schemas.moderation_event import ModerationDecisionEvent
from src.services.moderation_event_service import ModerationEventService

router = APIRouter(tags=["moderation-events"])


@router.post("/api/v1/events/moderation")
async def apply_moderation_event(
    event: ModerationDecisionEvent,
    _: None = Depends(verify_service_key),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    result = await ModerationEventService(db).apply(event)
    await db.commit()
    return result


@router.post("/api/v1/moderation/events")
async def apply_moderation_event_alias(
    event: ModerationDecisionEvent,
    _: None = Depends(verify_service_key),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    return await apply_moderation_event(event, _, db)
