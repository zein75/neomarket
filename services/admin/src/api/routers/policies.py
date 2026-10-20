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
from src.api.pagination import decode_cursor, encode_cursor, integer_cursor, string_cursor
from src.core.database import get_db
from src.models.admin_operation import AdminOperation
from src.models.admin_policy import AdminPolicy
from src.models.audit_log import AuditLog
from src.schemas.admin import AdminOperationResponse, PolicyInput, PublishInput
from src.schemas.admin_responses import PolicyPageResponse

router = APIRouter(route_class=AdminAPIRoute, tags=["policies"])


def _operation_response(operation: AdminOperation, request: Request) -> AdminOperationResponse:
    return AdminOperationResponse(
        operation_id=operation.id,
        status=operation.status,
        resource_id=operation.entity_id,
        request_id=getattr(request.state, "request_id", None),
        updated_at=operation.updated_at,
        version=operation.version,
    )


def _if_match(value: str) -> int:
    raw = value.strip().strip('"')
    if raw.startswith("v"):
        raw = raw[1:]
    try:
        version = int(raw)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "INVALID_IF_MATCH", "message": "If-Match must contain the policy version"}) from exc
    if version < 1:
        raise HTTPException(status_code=422, detail={"code": "INVALID_IF_MATCH", "message": "If-Match version must be positive"})
    return version


async def _propose(
    *, db: AsyncSession, request: Request, actor_id: UUID, key: UUID,
    action: str, policy_id: UUID, payload: dict[str, object], reason_code: str,
    request_hash: str,
) -> AdminOperationResponse:
    prior = await db.scalar(select(AdminOperation).where(
        AdminOperation.requested_by == actor_id,
        AdminOperation.idempotency_key == str(key),
    ))
    if prior is not None:
        if not hmac.compare_digest(prior.request_hash, request_hash):
            raise HTTPException(status_code=409, detail={"code": "IDEMPOTENCY_KEY_REUSED", "message": "Idempotency key was used for another operation"})
        return _operation_response(prior, request)
    operation = AdminOperation(
        id=uuid4(),
        action=action,
        entity_type="policy",
        entity_id=policy_id,
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
        entity_type="policy",
        entity_id=policy_id,
        details={"operation_id": str(operation.id), "reason_code": reason_code},
        created_at=datetime.now(timezone.utc),
    ))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        prior = await db.scalar(select(AdminOperation).where(
            AdminOperation.requested_by == actor_id,
            AdminOperation.idempotency_key == str(key),
        ))
        if prior is None or not hmac.compare_digest(prior.request_hash, request_hash):
            raise HTTPException(status_code=409, detail={"code": "IDEMPOTENCY_KEY_REUSED", "message": "Idempotency key conflicts with another operation"})
        operation = prior
    return _operation_response(operation, request)


@router.get("/admin/v1/policies", response_model=PolicyPageResponse, response_model_exclude_none=True)
async def list_policies(
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = Query(None, max_length=1024),
    _: SimpleNamespace = Depends(require_permission("policy.read")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    position = decode_cursor(cursor, string_cursor, integer_cursor, UUID)
    query = select(AdminPolicy)
    if position is not None:
        code, version, policy_id = position
        query = query.where(or_(
            AdminPolicy.code > code,
            and_(AdminPolicy.code == code, AdminPolicy.version < version),
            and_(AdminPolicy.code == code, AdminPolicy.version == version, AdminPolicy.id > policy_id),
        ))
    rows = list((await db.scalars(
        query.order_by(AdminPolicy.code, AdminPolicy.version.desc(), AdminPolicy.id).limit(limit + 1)
    )).all())
    has_more = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": [{"id": row.id, "code": row.code, "version": row.version, "status": row.status, "effective_at": row.effective_at, "content_hash": row.content_hash} for row in rows],
        "page": {"has_more": has_more, "next_cursor": encode_cursor(rows[-1].code, rows[-1].version, rows[-1].id) if has_more and rows else None},
    }


@router.post("/admin/v1/policies", response_model=AdminOperationResponse, status_code=202)
async def propose_policy(
    data: PolicyInput,
    request: Request,
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    actor: SimpleNamespace = Depends(require_permission("policy.write")),
    db: AsyncSession = Depends(get_db),
) -> AdminOperationResponse:
    payload = data.model_dump(mode="json")
    canonical_rules = json.dumps(data.rules, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    payload["content_hash"] = hashlib.sha256(canonical_rules.encode("utf-8")).hexdigest()
    request_hash = hashlib.sha256(json.dumps({"action": "POLICY_CREATE", "body": payload}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return await _propose(
        db=db, request=request, actor_id=actor.id, key=idempotency_key,
        action="POLICY_CREATE", policy_id=uuid4(), payload=payload,
        reason_code=data.reason_code, request_hash=request_hash,
    )


@router.post("/admin/v1/policies/{policy_id}/publish", response_model=AdminOperationResponse, status_code=202)
async def propose_policy_publish(
    policy_id: UUID,
    data: PublishInput,
    request: Request,
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    if_match: str = Header(alias="If-Match"),
    actor: SimpleNamespace = Depends(require_permission("policy.publish")),
    db: AsyncSession = Depends(get_db),
) -> AdminOperationResponse:
    expected_version = _if_match(if_match)
    policy = await db.scalar(select(AdminPolicy).where(AdminPolicy.id == policy_id))
    if policy is None:
        raise HTTPException(status_code=404, detail={"code": "POLICY_NOT_FOUND", "message": "Policy version not found"})
    if policy.version != expected_version:
        raise HTTPException(status_code=412, detail={"code": "VERSION_MISMATCH", "message": "Policy changed; reload before publishing"})
    if policy.status != "APPROVED":
        raise HTTPException(status_code=409, detail={"code": "POLICY_NOT_APPROVED", "message": "Only an independently approved policy can be published"})
    if not hmac.compare_digest(policy.content_hash, data.impact_hash.lower()):
        raise HTTPException(status_code=409, detail={"code": "POLICY_IMPACT_MISMATCH", "message": "Impact hash does not match the approved policy content"})
    payload = {
        "expected_policy_version": expected_version,
        "impact_hash": data.impact_hash.lower(),
        "approved_by": str(data.approved_by) if data.approved_by else None,
    }
    request_hash = hashlib.sha256(json.dumps({
        "action": "POLICY_PUBLISH", "policy_id": str(policy_id),
        "payload": payload, "reason_code": data.reason_code,
    }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return await _propose(
        db=db, request=request, actor_id=actor.id, key=idempotency_key,
        action="POLICY_PUBLISH", policy_id=policy_id, payload=payload,
        reason_code=data.reason_code, request_hash=request_hash,
    )
