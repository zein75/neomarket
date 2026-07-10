from types import SimpleNamespace
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_moderator
from src.core.database import get_db
from src.schemas.moderation import DeclineRequest, ModerationCardResponse
from src.services.moderation_service import ModerationService


router = APIRouter(tags=["moderation"])


@router.post(
    "/api/v1/moderation/{card_id}/approve",
    response_model=ModerationCardResponse,
)
@router.post(
    "/api/v1/products/{card_id}/approve",
    response_model=ModerationCardResponse,
    include_in_schema=False,
)
async def approve_product(
    card_id: UUID,
    current_moderator: SimpleNamespace = Depends(get_current_moderator),
    db: AsyncSession = Depends(get_db),
) -> ModerationCardResponse:
    card = await ModerationService(db).approve_product(card_id, current_moderator.id)
    await db.commit()
    return card


@router.post(
    "/api/v1/moderation/{card_id}/decline",
    response_model=ModerationCardResponse,
)
@router.post(
    "/api/v1/products/{card_id}/decline",
    response_model=ModerationCardResponse,
    include_in_schema=False,
)
async def decline_product(
    card_id: UUID,
    data: DeclineRequest,
    current_moderator: SimpleNamespace = Depends(get_current_moderator),
    db: AsyncSession = Depends(get_db),
) -> ModerationCardResponse:
    card = await ModerationService(db).decline_product(
        card_id,
        current_moderator.id,
        hard_block=data.hard_block,
        reason=data.reason,
        field_reports=data.field_reports,
    )
    await db.commit()
    return card


@router.post("/api/v1/events/products")
async def apply_product_event(
    event: dict[str, object],
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    result = await ModerationService(db).apply_product_event(event)
    await db.commit()
    return result
