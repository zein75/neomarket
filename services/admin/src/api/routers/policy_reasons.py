import hashlib
import hmac
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

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
from src.models.moderation import BlockingReason
from src.schemas.admin import AdminOperationResponse, ReasonInput, ReasonAction
from src.schemas.admin_responses import ReasonPageResponse

router = APIRouter(route_class=AdminAPIRoute, tags=["blocking-reasons"])


def _version(value: str) -> int:
    raw = value.strip().strip('"')
    if raw.startswith("v"):
        raw = raw[1:]
    try:
        parsed = int(raw)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "INVALID_IF_MATCH", "message": "If-Match must contain the reason version"}) from exc
    if parsed < 1:
        raise HTTPException(status_code=422, detail={"code": "INVALID_IF_MATCH", "message": "If-Match version must be positive"})
    return parsed


def _response(operation: AdminOperation, request: Request) -> AdminOperationResponse:
    return AdminOperationResponse(
        operation_id=operation.id,
        status=operation.status,
        resource_id=operation.entity_id,
        request_id=getattr(request.state, "request_id", None),
        updated_at=operation.updated_at,
        version=operation.version,
    )


async def _propose(
    *,
    db: AsyncSession,
    actor_id: UUID,
    key: UUID,
    request_hash: str,
    action: str,
    reason_id: UUID,
    payload: dict[str, object],
    reason_code: str,
    request: Request,
) -> AdminOperationResponse:
    previous = await db.scalar(select(AdminOperation).where(
        AdminOperation.requested_by == actor_id,
        AdminOperation.idempotency_key == str(key),
    ))
    if previous is not None:
        if not hmac.compare_digest(previous.request_hash, request_hash):
            raise HTTPException(status_code=409, detail={"code": "IDEMPOTENCY_KEY_REUSED", "message": "Idempotency key was used for another operation"})
        return _response(previous, request)
    operation = AdminOperation(
        action=action,
        entity_type="blocking_reason",
        entity_id=reason_id,
        payload=payload,
        status="WAITING_APPROVAL",
        version=1,
        idempotency_key=str(key),
        request_hash=request_hash,
        requested_by=actor_id,
        reason_code=reason_code,
        updated_at=datetime.now(timezone.utc),
    )
    db.add(operation)
    db.add(AuditLog(
        actor_id=actor_id,
        action=f"{action}_PROPOSED",
        entity_type="blocking_reason",
        entity_id=reason_id,
        details={"operation_id": str(operation.id), "reason_code": reason_code},
        created_at=datetime.now(timezone.utc),
    ))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        previous = await db.scalar(select(AdminOperation).where(
            AdminOperation.requested_by == actor_id,
            AdminOperation.idempotency_key == str(key),
        ))
        if previous is None or not hmac.compare_digest(previous.request_hash, request_hash):
            raise HTTPException(status_code=409, detail={"code": "IDEMPOTENCY_KEY_REUSED", "message": "Idempotency key conflicts with another operation"})
        operation = previous
    return _response(operation, request)


@router.get("/admin/v1/blocking-reasons", response_model=ReasonPageResponse, response_model_exclude_none=True)
async def list_reasons(
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = Query(None, max_length=1024),
    _: SimpleNamespace = Depends(require_permission("policy.reason.read")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    position = decode_cursor(cursor, datetime_cursor, UUID)
    query = select(BlockingReason)
    if position is not None:
        created_at, reason_id = position
        query = query.where(or_(
            BlockingReason.created_at > created_at,
            and_(BlockingReason.created_at == created_at, BlockingReason.id > reason_id),
        ))
    rows = list((await db.scalars(
        query.order_by(BlockingReason.created_at, BlockingReason.id).limit(limit + 1)
    )).all())
    has_more = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": [
            {
                "id": row.id,
                "code": row.code,
                "title": row.title,
                "description": row.description,
                "severity": row.severity,
                "active": row.is_active,
                "policy_version": row.version,
            }
            for row in rows
        ],
        "page": {"has_more": has_more, "next_cursor": encode_cursor(rows[-1].created_at, rows[-1].id) if has_more and rows else None},
    }


@router.post("/admin/v1/blocking-reasons", response_model=AdminOperationResponse, status_code=202)
async def create_reason(
    data: ReasonInput,
    request: Request,
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    actor: SimpleNamespace = Depends(require_permission("policy.reason.write")),
    db: AsyncSession = Depends(get_db),
) -> AdminOperationResponse:
    reason_id = uuid4()
    payload = data.model_dump(mode="json")
    request_hash = hashlib.sha256(json.dumps({"action": "CREATE", "payload": payload}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return await _propose(
        db=db, actor_id=actor.id, key=idempotency_key, request_hash=request_hash,
        action="BLOCKING_REASON_CREATE", reason_id=reason_id, payload=payload,
        reason_code="POLICY_REASON_CHANGE", request=request,
    )


@router.patch("/admin/v1/blocking-reasons/{reason_id}", response_model=AdminOperationResponse, status_code=202)
async def update_reason(
    reason_id: UUID,
    data: ReasonInput,
    request: Request,
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    if_match: str = Header(alias="If-Match"),
    actor: SimpleNamespace = Depends(require_permission("policy.reason.write")),
    db: AsyncSession = Depends(get_db),
) -> AdminOperationResponse:
    expected_version = _version(if_match)
    current = await db.scalar(select(BlockingReason).where(BlockingReason.id == reason_id))
    if current is None:
        raise HTTPException(status_code=404, detail={"code": "REASON_NOT_FOUND", "message": "Blocking reason not found"})
    if current.version != expected_version:
        raise HTTPException(status_code=412, detail={"code": "VERSION_MISMATCH", "message": "Reason changed; reload before editing"})
    payload = {**data.model_dump(mode="json", exclude_unset=True), "expected_reason_version": expected_version}
    request_hash = hashlib.sha256(json.dumps({"action": "UPDATE", "reason_id": str(reason_id), "payload": payload}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return await _propose(
        db=db, actor_id=actor.id, key=idempotency_key, request_hash=request_hash,
        action="BLOCKING_REASON_UPDATE", reason_id=reason_id, payload=payload,
        reason_code="POLICY_REASON_CHANGE", request=request,
    )


@router.post("/admin/v1/blocking-reasons/{reason_id}/archive", response_model=AdminOperationResponse, status_code=202)
async def archive_reason(
    reason_id: UUID,
    data: ReasonAction,
    request: Request,
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    if_match: str = Header(alias="If-Match"),
    actor: SimpleNamespace = Depends(require_permission("policy.reason.write")),
    db: AsyncSession = Depends(get_db),
) -> AdminOperationResponse:
    expected_version = _version(if_match)
    current = await db.scalar(select(BlockingReason).where(BlockingReason.id == reason_id))
    if current is None:
        raise HTTPException(status_code=404, detail={"code": "REASON_NOT_FOUND", "message": "Blocking reason not found"})
    if current.version != expected_version:
        raise HTTPException(status_code=412, detail={"code": "VERSION_MISMATCH", "message": "Reason changed; reload before archiving"})
    payload = {"expected_reason_version": expected_version}
    request_hash = hashlib.sha256(json.dumps({"action": "ARCHIVE", "reason_id": str(reason_id), "payload": payload, "reason_code": data.reason_code, "comment": data.comment}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return await _propose(
        db=db, actor_id=actor.id, key=idempotency_key, request_hash=request_hash,
        action="BLOCKING_REASON_ARCHIVE", reason_id=reason_id, payload=payload,
        reason_code=data.reason_code, request=request,
    )
