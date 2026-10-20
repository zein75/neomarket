import hashlib
import hmac
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import require_permission
from src.api.router import AdminAPIRoute
from src.api.pagination import datetime_cursor, decode_cursor, encode_cursor
from src.core.database import get_db
from src.models.admin_operation import AdminOperation
from src.models.audit_log import AuditLog
from src.models.moderation_outbox_event import ModerationOutboxEvent
from src.schemas.admin import AdminOperationResponse, ReasonAction
from src.schemas.admin_responses import OutboxPageResponse

router = APIRouter(route_class=AdminAPIRoute, tags=["operations"])


def _response(operation: AdminOperation, request: Request) -> AdminOperationResponse:
    return AdminOperationResponse(
        operation_id=operation.id,
        status=operation.status,
        resource_id=operation.entity_id,
        request_id=getattr(request.state, "request_id", None),
        updated_at=operation.updated_at,
        version=operation.version,
    )


@router.get("/admin/v1/operations/events", response_model=OutboxPageResponse, response_model_exclude_none=True)
async def list_outbox_events(
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = Query(None, max_length=1024),
    actor: SimpleNamespace = Depends(require_permission("operations.events.read")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    position = decode_cursor(cursor, datetime_cursor, UUID)
    query = select(ModerationOutboxEvent)
    if position is not None:
        created_at, event_id = position
        query = query.where(or_(
            ModerationOutboxEvent.created_at < created_at,
            and_(ModerationOutboxEvent.created_at == created_at, ModerationOutboxEvent.id < event_id),
        ))
    rows = list((await db.scalars(
        query.order_by(ModerationOutboxEvent.created_at.desc(), ModerationOutboxEvent.id.desc()).limit(limit + 1)
    )).all())
    has_more = len(rows) > limit
    rows = rows[:limit]
    response = {
        "items": [
            {
                "id": row.id,
                "event_type": row.event_type,
                "status": row.status,
                "attempts": row.attempts,
                "last_error": "DELIVERY_FAILED" if row.last_error else None,
                "created_at": row.created_at,
            }
            for row in rows
        ],
        "page": {
            "has_more": has_more,
            "next_cursor": encode_cursor(rows[-1].created_at, rows[-1].id) if has_more and rows else None,
        },
    }
    db.add(AuditLog(
        actor_id=actor.id,
        action="OUTBOX_EVENTS_LIST_READ",
        entity_type="outbox_event_collection",
        entity_id=actor.id,
        details={"returned_count": len(rows), "has_more": has_more},
        created_at=datetime.now(timezone.utc),
    ))
    await db.commit()
    return response


@router.post("/admin/v1/operations/events/{event_id}/retry", response_model=AdminOperationResponse, status_code=202)
async def propose_outbox_retry(
    event_id: UUID,
    data: ReasonAction,
    request: Request,
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    actor: SimpleNamespace = Depends(require_permission("operations.events.retry")),
    db: AsyncSession = Depends(get_db),
) -> AdminOperationResponse:
    prior = await db.scalar(select(AdminOperation).where(
        AdminOperation.requested_by == actor.id,
        AdminOperation.idempotency_key == str(idempotency_key),
    ))
    request_hash = hashlib.sha256(json.dumps({
        "event_id": str(event_id), "reason_code": data.reason_code,
        "comment": data.comment,
    }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if prior is not None:
        if (
            prior.action != "OUTBOX_RETRY"
            or prior.entity_type != "outbox_event"
            or prior.entity_id != event_id
            or not hmac.compare_digest(prior.request_hash, request_hash)
        ):
            raise HTTPException(status_code=409, detail={"code": "IDEMPOTENCY_KEY_REUSED", "message": "Idempotency key was used for another operation"})
        return _response(prior, request)
    event = await db.scalar(select(ModerationOutboxEvent).where(ModerationOutboxEvent.id == event_id))
    if event is None:
        raise HTTPException(status_code=404, detail={"code": "EVENT_NOT_FOUND", "message": "Outbox event not found"})
    if event.status not in {"DEAD", "RETRY"}:
        raise HTTPException(status_code=409, detail={"code": "EVENT_NOT_RETRYABLE", "message": "Only retryable or dead-letter events can be retried"})
    operation = AdminOperation(
        action="OUTBOX_RETRY",
        entity_type="outbox_event",
        entity_id=event.id,
        payload={"expected_status": event.status, "expected_attempts": event.attempts},
        status="WAITING_APPROVAL",
        version=1,
        idempotency_key=str(idempotency_key),
        request_hash=request_hash,
        requested_by=actor.id,
        reason_code=data.reason_code,
        updated_at=datetime.now(timezone.utc),
    )
    db.add(operation)
    db.add(AuditLog(
        actor_id=actor.id,
        action="OUTBOX_RETRY_PROPOSED",
        entity_type="outbox_event",
        entity_id=event.id,
        details={"operation_id": str(operation.id), "reason_code": data.reason_code},
        created_at=datetime.now(timezone.utc),
    ))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        prior = await db.scalar(select(AdminOperation).where(
            AdminOperation.requested_by == actor.id,
            AdminOperation.idempotency_key == str(idempotency_key),
        ))
        if (
            prior is None
            or prior.action != "OUTBOX_RETRY"
            or prior.entity_type != "outbox_event"
            or prior.entity_id != event_id
            or not hmac.compare_digest(prior.request_hash, request_hash)
        ):
            raise HTTPException(status_code=409, detail={"code": "IDEMPOTENCY_KEY_REUSED", "message": "Idempotency key conflicts with another operation"})
        operation = prior
    return _response(operation, request)
