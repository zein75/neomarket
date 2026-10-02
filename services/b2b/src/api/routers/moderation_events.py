from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db, verify_service_key
from src.schemas.moderation_event import (
    BlockingReason,
    ModerationDecisionEvent,
    ModerationEventRequest,
)
from src.services.moderation_event_service import ModerationEventService

router = APIRouter(tags=["moderation-events"])


def _decision_event(event: ModerationEventRequest) -> ModerationDecisionEvent:
    blocking_reason = None
    if event.event_type.value == "BLOCKED" and event.blocking_reason_id:
        reason_metadata = (event.model_extra or {}).get("blocking_reason")
        if isinstance(reason_metadata, dict):
            blocking_reason = BlockingReason.model_validate(reason_metadata)
        else:
            seller_reason = event.moderator_comment or next(
                (report.comment for report in event.field_reports if report.comment),
                "Reason details unavailable",
            )
            blocking_reason = BlockingReason(
                id=event.blocking_reason_id,
                title=seller_reason,
                comment=event.moderator_comment or seller_reason,
            )
    return ModerationDecisionEvent(
        idempotency_key=event.idempotency_key,
        product_id=event.product_id,
        status=event.event_type,
        occurred_at=event.occurred_at,
        hard_block=event.hard_block if event.event_type.value == "BLOCKED" else None,
        blocking_reason=blocking_reason,
        field_reports=event.field_reports if event.event_type.value == "BLOCKED" else None,
    )


@router.post("/api/v1/moderation/events", status_code=status.HTTP_204_NO_CONTENT)
@router.post(
    "/api/v1/events/moderation",
    status_code=status.HTTP_204_NO_CONTENT,
    include_in_schema=False,
)
async def apply_moderation_event(
    event: ModerationEventRequest,
    _: None = Depends(verify_service_key),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await ModerationEventService(db).apply(_decision_event(event))
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
