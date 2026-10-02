import httpx
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db, verify_service_key
from src.clients.moderation import ModerationClient
from src.schemas.moderation_event import (
    BlockingReason,
    ModerationDecisionEvent,
    ModerationEventRequest,
)
from src.services.moderation_event_service import ModerationEventService

router = APIRouter(tags=["moderation-events"])


async def _decision_event(event: ModerationEventRequest) -> ModerationDecisionEvent:
    blocking_reason = None
    if event.event_type.value == "BLOCKED" and event.blocking_reason_id:
        try:
            reason_metadata = await ModerationClient().get_blocking_reason(
                str(event.blocking_reason_id)
            )
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "MODERATION_UNAVAILABLE",
                    "message": "Blocking reason service is unavailable",
                },
            ) from exc
        if not reason_metadata or not reason_metadata.get("title"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "BLOCKING_REASON_NOT_FOUND",
                    "message": "Blocking reason not found",
                },
            )
        if event.moderator_comment:
            reason_metadata["comment"] = event.moderator_comment
        blocking_reason = BlockingReason.model_validate(reason_metadata)
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
    await ModerationEventService(db).apply(await _decision_event(event))
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
