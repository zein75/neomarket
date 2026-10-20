import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db, verify_service_key
from src.api.routers.admin_internal import verify_admin_service
from src.clients.moderation import ModerationClient
from src.models.inbox_event import InboxEvent
from src.schemas.moderation_event import (
    AdminModerationDecisionRequest,
    BlockingReason,
    ModerationDecisionEvent,
    ModerationEventRequest,
    ModerationEventEnvelope,
)
from src.services.moderation_event_service import ModerationEventService

router = APIRouter(tags=["moderation-events"])


@router.post(
    "/internal/v1/moderation/decisions",
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="post__internal_v1_moderation_decisions",
    openapi_extra={"x-allowed-service": "service:admin"},
)
async def accept_admin_moderation_decision(
    data: AdminModerationDecisionRequest,
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    if_match: str = Header(alias="If-Match"),
    _: None = Depends(verify_admin_service),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if idempotency_key != data.correlation_id:
        raise HTTPException(
            status_code=422,
            detail={"code": "IDEMPOTENCY_KEY_MISMATCH", "message": "Idempotency-Key must equal correlation_id"},
        )
    try:
        expected_revision = int(if_match.strip().strip('"').removeprefix("v"))
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_IF_MATCH", "message": "If-Match must contain submitted revision"},
        ) from exc
    if expected_revision != data.submitted_revision:
        raise HTTPException(
            status_code=412,
            detail={"code": "REVISION_HEADER_MISMATCH", "message": "If-Match must equal submitted_revision"},
        )

    action = data.action
    blocked = action != "APPROVE"
    event = ModerationDecisionEvent(
        idempotency_key=data.correlation_id,
        decision_id=data.decision_id,
        product_id=data.product_id,
        seller_id=data.seller_id,
        snapshot_hash=data.snapshot_hash,
        status="BLOCKED" if blocked else "MODERATED",
        occurred_at=datetime.now(timezone.utc),
        reviewed_revision=data.submitted_revision,
        action=action,
        reason_code=data.reason_codes[0] if data.reason_codes else None,
        hard_block=(action == "HARD_BLOCK") if blocked else None,
        field_reports=[
            {
                "field_name": report.field_path,
                "reason_code": report.reason_code,
                "sku_id": report.sku_id,
                "media_id": report.media_id,
                "comment": report.comment,
            }
            for report in data.field_reports
        ] or None,
    )
    await ModerationEventService(db).apply(event)
    await db.commit()
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={"command_id": str(data.decision_id), "status": "QUEUED"},
    )


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
        actor_id=event.moderator_id,
        action="APPROVE" if event.event_type.value == "MODERATED" else "BLOCK",
        reason_code=str(event.blocking_reason_id) if event.blocking_reason_id else None,
        comment=event.moderator_comment,
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
        reviewed_revision=event.payload.reviewed_revision,
        ticket_id=event.payload.ticket_id,
        actor_id=event.payload.actor_id,
        action=action,
        reason_code=event.payload.reason_code,
        comment=event.payload.comment,
        hard_block=(action == "HARD_BLOCK") if status_value == "BLOCKED" else None,
        field_reports=[
            {
                "field_name": report.field_path,
                "reason_code": report.reason_code,
                "sku_id": report.sku_id,
                "comment": report.comment,
            }
            for report in event.payload.field_reports
        ] or None,
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
        reviewed_revision=event.payload.reviewed_revision,
        ticket_id=event.payload.ticket_id,
        actor_id=event.payload.actor_id,
        action=action,
        reason_code=event.payload.reason_code,
        comment=event.payload.comment,
        hard_block=action == "HARD_BLOCK" if action != "APPROVE" else None,
        field_reports=None,
    )
    await ModerationEventService(db).apply(decision)
    receipt.status = "PROCESSED"
    receipt.processed_at = datetime.now(timezone.utc)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
