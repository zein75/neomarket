import hashlib
import json
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db, verify_service_key
from src.clients.moderation import ModerationClient
from src.models.inbox_event import InboxEvent
from src.schemas.moderation_event import (
    BlockingReason,
    ModerationDecisionEvent,
    ModerationEventRequest,
    ModerationEventEnvelope,
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
            # The frozen wire contract for this endpoint declares only 204,
            # 400 and 401.  A reason lookup failure therefore remains a
            # contract-valid rejected event; the moderation producer owns the
            # retry rather than receiving an undeclared 503.
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "BLOCKING_REASON_LOOKUP_FAILED",
                    "message": "Blocking reason could not be resolved",
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


@router.post(
    "/internal/v1/events/moderation",
    status_code=status.HTTP_202_ACCEPTED,
    responses={200: {"description": "Already applied"}},
)
async def apply_moderation_event_envelope_canonical(
    event: ModerationEventEnvelope,
    _: None = Depends(verify_service_key),
    db: AsyncSession = Depends(get_db),
) -> Response:
    action = event.payload.action
    status_value = "BLOCKED" if action in {"BLOCK", "HARD_BLOCK"} else "MODERATED"
    decision = ModerationDecisionEvent(
        idempotency_key=event.event_id,
        product_id=event.payload.product_id,
        status=status_value,
        occurred_at=event.occurred_at,
        hard_block=(action == "HARD_BLOCK") if status_value == "BLOCKED" else None,
        field_reports=None,
    )
    result = await ModerationEventService(db).apply(decision)
    await db.commit()
    return Response(
        status_code=(status.HTTP_200_OK if result.get("status") == "DUPLICATE" else status.HTTP_202_ACCEPTED)
    )


@router.post("/api/v1/moderation/events", status_code=status.HTTP_204_NO_CONTENT, include_in_schema=False)
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


@router.post(
    "/api/v1/moderation/events/envelope",
    status_code=status.HTTP_204_NO_CONTENT,
    include_in_schema=False,
)
async def apply_moderation_event_envelope(
    event: ModerationEventEnvelope,
    _: None = Depends(verify_service_key),
    db: AsyncSession = Depends(get_db),
) -> Response:
    payload_hash = hashlib.sha256(
        json.dumps(
            event.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    existing = await db.execute(
        select(InboxEvent).where(
            InboxEvent.producer == event.producer,
            InboxEvent.event_id == event.event_id,
        )
    )
    receipt = existing.scalar_one_or_none()
    if receipt is not None:
        if receipt.payload_hash != payload_hash:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "EVENT_ID_CONFLICT",
                    "message": "event_id was reused with different payload",
                },
            )
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    receipt = InboxEvent(
        producer=event.producer,
        event_id=event.event_id,
        payload_hash=payload_hash,
        received_at=datetime.now(timezone.utc),
    )
    db.add(receipt)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raced = await db.execute(
            select(InboxEvent).where(
                InboxEvent.producer == event.producer,
                InboxEvent.event_id == event.event_id,
            )
        )
        raced_receipt = raced.scalar_one_or_none()
        if raced_receipt is not None and raced_receipt.payload_hash != payload_hash:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "EVENT_ID_CONFLICT",
                    "message": "event_id was reused with different payload",
                },
            )
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    action = event.payload.action
    status_value = "MODERATED" if action == "APPROVE" else "BLOCKED"
    decision = ModerationDecisionEvent(
        idempotency_key=event.event_id,
        product_id=event.payload.product_id,
        status=status_value,
        occurred_at=event.occurred_at,
        hard_block=action == "HARD_BLOCK" if action != "APPROVE" else None,
        field_reports=None,
    )
    await ModerationEventService(db).apply(decision)
    receipt.status = "PROCESSED"
    receipt.processed_at = datetime.now(timezone.utc)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
