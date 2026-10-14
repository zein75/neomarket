import base64
from types import SimpleNamespace
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_moderator, verify_service_key
from src.core.database import get_db
from src.schemas.moderation import (
    BlockDecisionRequest,
    BlockingReasonResponse,
    ModerationCardResponse,
    ProductEventRequest,
    TicketResponse,
    DecisionRequest,
    DecisionResult,
    ProductEventEnvelope,
)
from src.models.moderation import ModerationCard, ModerationStatus
from src.models.audit_log import AuditLog
from src.services.moderation_service import ModerationService


router = APIRouter(tags=["moderation"])


@router.get("/admin/v1/audit-events")
async def list_audit_events(
    cursor: int = Query(0, ge=0, le=10_000),
    limit: int = Query(20, ge=1, le=100),
    _: SimpleNamespace = Depends(get_current_moderator),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, object]]:
    result = await db.execute(
        select(AuditLog)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .offset(cursor)
        .limit(limit)
    )
    return [
        {
            "id": str(item.id),
            "actor_id": str(item.actor_id) if item.actor_id else None,
            "action": item.action,
            "entity_type": item.entity_type,
            "entity_id": str(item.entity_id),
            "details": item.details,
            "created_at": item.created_at,
        }
        for item in result.scalars().all()
    ]


def _cursor_offset(cursor: str | None) -> int:
    if not isinstance(cursor, str) or not cursor:
        return 0
    try:
        offset = int(base64.urlsafe_b64decode(cursor.encode("ascii")).decode("ascii"))
    except (ValueError, UnicodeDecodeError, base64.binascii.Error) as exc:
        raise HTTPException(status_code=422, detail={"code": "INVALID_CURSOR", "message": "Invalid ticket cursor"}) from exc
    if offset < 0 or offset > 10_000:
        raise HTTPException(status_code=422, detail={"code": "INVALID_CURSOR", "message": "Invalid ticket cursor"})
    return offset


def _ticket_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(str(offset).encode("ascii")).decode("ascii")


@router.get("/admin/v1/moderation/tickets")
@router.get("/api/v1/tickets", include_in_schema=False)
async def list_tickets(
    cursor: str | None = Query(None, max_length=1024),
    limit: int = Query(20, ge=1, le=100),
    status_filter: ModerationStatus | None = Query(None, alias="status"),
    _: SimpleNamespace = Depends(get_current_moderator),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    offset = _cursor_offset(cursor)
    items, total = await ModerationService(db).list_tickets(
        limit=limit,
        offset=offset,
        status_filter=status_filter,
    )
    next_offset = offset + limit
    return {
        "items": [TicketResponse.model_validate(item) for item in items],
        "page": {
            "has_more": next_offset < total,
            "next_cursor": _ticket_cursor(next_offset) if next_offset < total else None,
        },
    }


@router.get("/admin/v1/moderation/tickets/{ticket_id}", response_model=ModerationCardResponse)
async def get_ticket(
    ticket_id: UUID,
    _: SimpleNamespace = Depends(get_current_moderator),
    db: AsyncSession = Depends(get_db),
) -> ModerationCardResponse:
    card = await ModerationService(db).repo.get_with_skus(ticket_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Moderation card not found")
    return ModerationCardResponse.model_validate(card)


@router.get("/admin/v1/moderation/tickets/{ticket_id}/history")
async def get_ticket_history(
    ticket_id: UUID,
    _: SimpleNamespace = Depends(get_current_moderator),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, object]]:
    exists = await db.scalar(
        select(ModerationCard.id).where(ModerationCard.id == ticket_id)
    )
    if exists is None:
        raise HTTPException(status_code=404, detail="Moderation card not found")
    result = await db.execute(
        select(AuditLog)
        .where(AuditLog.entity_id == ticket_id)
        .order_by(AuditLog.created_at.asc(), AuditLog.id.asc())
    )
    return [
        {
            "id": str(item.id),
            "action": item.action,
            "actor_id": str(item.actor_id) if item.actor_id else None,
            "details": item.details,
            "created_at": item.created_at,
        }
        for item in result.scalars().all()
    ]


@router.post("/admin/v1/moderation/tickets/{ticket_id}/claim", response_model=ModerationCardResponse)
@router.post("/api/v1/tickets/{ticket_id}/claim", response_model=ModerationCardResponse, include_in_schema=False)
async def claim_ticket(
    ticket_id: UUID,
    current_moderator: SimpleNamespace = Depends(get_current_moderator),
    db: AsyncSession = Depends(get_db),
) -> ModerationCardResponse:
    card = await ModerationService(db).claim_ticket(ticket_id, current_moderator.id)
    await db.commit()
    return card


@router.post("/admin/v1/moderation/tickets/{ticket_id}/release", response_model=ModerationCardResponse)
@router.post("/api/v1/tickets/{ticket_id}/release", response_model=ModerationCardResponse, include_in_schema=False)
async def release_ticket(
    ticket_id: UUID,
    current_moderator: SimpleNamespace = Depends(get_current_moderator),
    db: AsyncSession = Depends(get_db),
) -> ModerationCardResponse:
    card = await ModerationService(db).release_ticket(ticket_id, current_moderator.id)
    await db.commit()
    return card


@router.post("/admin/v1/moderation/tickets/{ticket_id}/heartbeat", response_model=ModerationCardResponse)
@router.post("/api/v1/tickets/{ticket_id}/heartbeat", response_model=ModerationCardResponse, include_in_schema=False)
async def heartbeat_ticket(
    ticket_id: UUID,
    current_moderator: SimpleNamespace = Depends(get_current_moderator),
    db: AsyncSession = Depends(get_db),
) -> ModerationCardResponse:
    card = await ModerationService(db).heartbeat_ticket(ticket_id, current_moderator.id)
    await db.commit()
    return card


@router.post("/admin/v1/moderation/tickets/{ticket_id}/decisions", response_model=DecisionResult, status_code=202)
async def decide_ticket(
    ticket_id: UUID,
    data: DecisionRequest,
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    current_moderator: SimpleNamespace = Depends(get_current_moderator),
    db: AsyncSession = Depends(get_db),
) -> DecisionResult:
    service = ModerationService(db)
    if data.action == "APPROVE":
        await service.approve_product(ticket_id, current_moderator.id)
    else:
        reasons = await service.list_blocking_reasons()
        reason = next((item for item in reasons if item.code == data.reason_code), None)
        if reason is None:
            raise HTTPException(status_code=422, detail="reason_code is required and must be active")
        await service.block_product(
            ticket_id,
            current_moderator.id,
            blocking_reason_ids=[reason.id],
            comment=data.comment,
            field_reports=None,
        )
    await db.commit()
    return DecisionResult(decision_id=idempotency_key, status="APPLIED", ticket_id=ticket_id)


@router.post("/api/v1/tickets/{ticket_id}/approve", response_model=ModerationCardResponse, include_in_schema=False)
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
    "/admin/v1/moderation/tickets/{ticket_id}/decisions/block",
    response_model=ModerationCardResponse,
)
@router.post("/api/v1/tickets/{ticket_id}/block", response_model=ModerationCardResponse, include_in_schema=False)
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
    "/admin/v1/blocking-reasons",
    response_model=list[BlockingReasonResponse],
)
@router.get("/api/v1/blocking-reasons", response_model=list[BlockingReasonResponse], include_in_schema=False)
async def list_blocking_reasons(
    hard_block: bool | None = None,
    _: SimpleNamespace = Depends(get_current_moderator),
    db: AsyncSession = Depends(get_db),
) -> list[BlockingReasonResponse]:
    return await ModerationService(db).list_blocking_reasons(hard_block=hard_block)


@router.post(
    "/internal/v1/events/products",
    status_code=202,
    responses={200: {"description": "Already applied"}},
)
async def apply_product_event_envelope(
    event: ProductEventEnvelope,
    _: None = Depends(verify_service_key),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    event_type = {
        "product.deleted": "PRODUCT_DELETED",
        "product.updated": "PRODUCT_EDITED",
        "product.created": "PRODUCT_CREATED",
    }[event.event_type]
    result = await ModerationService(db).apply_product_event(
        {
            "event_type": event_type,
            "product_id": str(event.aggregate_id),
            "idempotency_key": str(event.event_id),
            "occurred_at": event.occurred_at,
            "payload": event.payload,
        }
    )
    await db.commit()
    return result


@router.post("/api/v1/b2b/events", include_in_schema=False)
@router.post("/api/v1/events/products", include_in_schema=False)
async def apply_product_event(
    event: ProductEventRequest,
    _: None = Depends(verify_service_key),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    result = await ModerationService(db).apply_product_event(event.model_dump(mode="json"))
    await db.commit()
    return result
