from types import SimpleNamespace
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_moderator, verify_service_key
from src.core.database import get_db
from src.schemas.moderation import (
    BlockDecisionRequest,
    BlockingReasonResponse,
    ModerationCardResponse,
)
from src.services.moderation_service import ModerationService


router = APIRouter(tags=["moderation"])


@router.post(
    "/api/v1/tickets/{ticket_id}/approve",
    response_model=ModerationCardResponse,
)
async def approve_ticket(
    ticket_id: UUID,
    current_moderator: SimpleNamespace = Depends(get_current_moderator),
    db: AsyncSession = Depends(get_db),
) -> ModerationCardResponse:
    card = await ModerationService(db).approve_product(ticket_id, current_moderator.id)
    await db.commit()
    return card


@router.post(
    "/api/v1/moderation/{card_id}/approve",
    response_model=ModerationCardResponse,
    include_in_schema=False,
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
    "/api/v1/tickets/{ticket_id}/block",
    response_model=ModerationCardResponse,
)
async def block_ticket(
    ticket_id: UUID,
    data: BlockDecisionRequest,
    current_moderator: SimpleNamespace = Depends(get_current_moderator),
    db: AsyncSession = Depends(get_db),
) -> ModerationCardResponse:
    card = await ModerationService(db).block_product(
        ticket_id,
        current_moderator.id,
        blocking_reason_ids=data.blocking_reason_ids,
        comment=data.comment,
        field_reports=data.field_reports,
    )
    await db.commit()
    return card


@router.get(
    "/api/v1/blocking-reasons",
    response_model=list[BlockingReasonResponse],
)
async def list_blocking_reasons(
    hard_block: bool | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[BlockingReasonResponse]:
    return await ModerationService(db).list_blocking_reasons(hard_block=hard_block)


@router.post("/api/v1/b2b/events")
@router.post("/api/v1/events/products", include_in_schema=False)
async def apply_product_event(
    event: dict[str, object],
    _: None = Depends(verify_service_key),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    result = await ModerationService(db).apply_product_event(event)
    await db.commit()
    return result
