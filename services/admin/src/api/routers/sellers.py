import hashlib
import hmac
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.pagination import datetime_cursor, decode_cursor, encode_cursor
from src.api.deps import require_permission
from src.api.router import AdminAPIRoute
from src.clients.b2b_client import B2BClient
from src.core.database import get_db
from src.models.admin_operation import AdminOperation
from src.models.audit_log import AuditLog
from src.schemas.admin import AdminOperationResponse
from src.schemas.sellers import SellerRestrictionInput
from src.schemas.moderation import AuditPage
from src.schemas.taxonomy import PageResponse
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

router = APIRouter(route_class=AdminAPIRoute, tags=["sellers"])


class SellerCaseResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    seller_id: UUID
    status: Literal["UNDER_REVIEW", "ACTIVE", "RESTRICTED", "SUSPENDED", "TERMINATED"]
    reason_code: str | None = Field(default=None)
    version: int = Field(ge=1)
    updated_at: datetime = Field(default=None)


class SellerPageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[SellerCaseResponse]
    page: PageResponse


@router.get("/admin/v1/sellers", response_model=SellerPageResponse, response_model_exclude_none=True, operation_id="GET_admin_v1_sellers", responses={503: {"description": "Seller review is not configured"}})
async def list_sellers(
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    _: SimpleNamespace = Depends(require_permission("seller.review.read")),
) -> SellerPageResponse:
    body = await B2BClient().get_internal_json(
        "/internal/v1/sellers",
        params={key: value for key, value in {"cursor": cursor, "limit": limit}.items() if value is not None},
    )
    try:
        return SellerPageResponse.model_validate(body)
    except ValueError as exc:
        raise HTTPException(status_code=502, detail={"code": "B2B_INVALID_RESPONSE", "message": "B2B returned an invalid seller page"}) from exc


@router.get("/admin/v1/sellers/{seller_id}", response_model=SellerCaseResponse, operation_id="GET_admin_v1_sellers_seller_id", responses={503: {"description": "Seller review is not configured"}})
async def get_seller(
    seller_id: UUID,
    _: SimpleNamespace = Depends(require_permission("seller.review.read")),
) -> SellerCaseResponse:
    body = await B2BClient().get_internal_json(f"/internal/v1/sellers/{seller_id}")
    try:
        return SellerCaseResponse.model_validate(body)
    except ValueError as exc:
        raise HTTPException(status_code=502, detail={"code": "B2B_INVALID_RESPONSE", "message": "B2B returned an invalid seller case"}) from exc


@router.get("/admin/v1/sellers/{seller_id}/history", response_model=AuditPage, response_model_exclude_none=True, operation_id="GET_admin_v1_sellers_seller_id_history")
async def get_seller_history(
    seller_id: UUID,
    cursor: str | None = Query(None, max_length=1024),
    limit: int = Query(default=20, ge=1, le=100),
    actor: SimpleNamespace = Depends(require_permission("seller.review.read")),
    db: AsyncSession = Depends(get_db),
) -> AuditPage:
    position = decode_cursor(cursor, datetime_cursor, UUID)
    query = select(AuditLog).where(
        AuditLog.entity_type == "seller",
        AuditLog.entity_id == seller_id,
    )
    if position is not None:
        created_at, event_id = position
        query = query.where(
            (AuditLog.created_at < created_at)
            | ((AuditLog.created_at == created_at) & (AuditLog.id < event_id))
        )
    result = await db.execute(
        query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit + 1)
    )
    rows = list(result.scalars().all())
    has_more = len(rows) > limit
    rows = rows[:limit]
    db.add(AuditLog(
        actor_id=actor.id,
        action="SELLER_HISTORY_READ",
        entity_type="seller",
        entity_id=seller_id,
        details={"returned_count": len(rows), "has_more": has_more},
        created_at=datetime.now(timezone.utc),
    ))
    await db.commit()
    return AuditPage(
        items=[
            {
                "id": event.id,
                "action": event.action,
                "actor_id": event.actor_id,
                "entity_type": event.entity_type,
                "entity_id": event.entity_id,
                "created_at": event.created_at,
                "request_id": event.request_id,
                # Keep seller history summary-only; unrestricted event details
                # may include operational or personal data.
                "redacted_details": {},
            }
            for event in rows
        ],
        page={
            "has_more": has_more,
            "next_cursor": encode_cursor(rows[-1].created_at, rows[-1].id) if has_more and rows else None,
        },
    )


def _response(operation: AdminOperation, request: Request) -> AdminOperationResponse:
    return AdminOperationResponse(
        operation_id=operation.id,
        status=operation.status,
        resource_id=operation.entity_id,
        request_id=getattr(request.state, "request_id", None),
        updated_at=operation.updated_at,
        version=operation.version,
    )


def _expected_version(value: str) -> int:
    try:
        version = int(value.strip().strip('"').removeprefix("v"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "INVALID_IF_MATCH", "message": "If-Match must contain a positive seller version"}) from exc
    if version < 1:
        raise HTTPException(status_code=422, detail={"code": "INVALID_IF_MATCH", "message": "If-Match must contain a positive seller version"})
    return version


@router.post("/admin/v1/sellers/{seller_id}/restrictions", response_model=AdminOperationResponse, status_code=202, operation_id="POST_admin_v1_sellers_seller_id_restrictions")
async def propose_seller_restriction(
    seller_id: UUID,
    data: SellerRestrictionInput,
    request: Request,
    if_match: str = Header(alias="If-Match"),
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    actor: SimpleNamespace = Depends(require_permission("seller.restrict")),
    db: AsyncSession = Depends(get_db),
) -> AdminOperationResponse:
    expected_version = _expected_version(if_match)
    if data.effective_until is not None and data.effective_until <= datetime.now(timezone.utc):
        raise HTTPException(status_code=422, detail={"code": "INVALID_RESTRICTION_EXPIRY", "message": "Restriction expiry must be in the future"})
    if data.action == "SUSPEND" and data.effective_until is None:
        raise HTTPException(status_code=422, detail={"code": "SUSPENSION_EXPIRY_REQUIRED", "message": "Seller suspension must have an expiry"})
    body = data.model_dump(mode="json")
    request_hash = hashlib.sha256(json.dumps({
        "seller_id": str(seller_id), "expected_version": expected_version, "body": body,
    }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    prior = await db.scalar(select(AdminOperation).where(
        AdminOperation.requested_by == actor.id,
        AdminOperation.idempotency_key == str(idempotency_key),
    ))
    if prior is not None:
        if prior.action != "SELLER_RESTRICTION" or not hmac.compare_digest(prior.request_hash, request_hash):
            raise HTTPException(status_code=409, detail={"code": "IDEMPOTENCY_KEY_REUSED", "message": "Idempotency key was used for a different operation"})
        return _response(prior, request)
    operation = AdminOperation(
        id=uuid4(), action="SELLER_RESTRICTION", entity_type="seller", entity_id=seller_id,
        payload={"expected_version": expected_version, "command_payload": body},
        status="WAITING_APPROVAL", version=1, idempotency_key=str(idempotency_key),
        request_hash=request_hash, requested_by=actor.id, reason_code=data.reason_code,
        updated_at=datetime.now(timezone.utc),
    )
    db.add(operation)
    db.add(AuditLog(
        actor_id=actor.id, action="SELLER_RESTRICTION_PROPOSED", entity_type="seller", entity_id=seller_id,
        details={"operation_id": str(operation.id), "action": data.action, "reason_code": data.reason_code,
                 "expected_version": expected_version},
        created_at=datetime.now(timezone.utc),
    ))
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        prior = await db.scalar(select(AdminOperation).where(
            AdminOperation.requested_by == actor.id,
            AdminOperation.idempotency_key == str(idempotency_key),
        ))
        if prior is not None and prior.action == "SELLER_RESTRICTION" and hmac.compare_digest(prior.request_hash, request_hash):
            return _response(prior, request)
        raise HTTPException(status_code=409, detail={"code": "OPERATION_CONFLICT", "message": "Seller restriction could not be recorded"}) from exc
    return _response(operation, request)
