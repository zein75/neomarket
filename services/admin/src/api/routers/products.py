import hashlib
import hmac
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from urllib.parse import urlencode
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import require_permission
from src.api.router import AdminAPIRoute
from src.clients.b2b_client import B2BClient
from src.core.config import settings
from src.core.database import get_db
from src.models.admin_operation import AdminOperation
from src.models.audit_log import AuditLog
from src.models.moderation import ModerationCard, ModerationSKU, ModerationStatus
from src.models.moderation_outbox_event import ModerationOutboxEvent
from src.models.moderation_snapshot import ModerationSnapshot
from src.schemas.admin import AdminOperationResponse, ReasonAction
from src.schemas.products import B2BProductPage, HoldInput, ProductOverview, ProductPageResponse, ProductPublication, ProductRevisionSnapshot
from src.schemas.taxonomy import PageResponse
from src.services.product_snapshots import content_digest, normalize_source_digest

router = APIRouter(route_class=AdminAPIRoute, tags=["products"])


@router.get("/admin/v1/products", response_model=ProductPageResponse, response_model_exclude_none=True, operation_id="GET_admin_v1_products", responses={503: {"description": "B2B service unavailable"}})
async def list_products(
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None, max_length=200),
    _: SimpleNamespace = Depends(require_permission("products.read")),
) -> ProductPageResponse:
    params = {"limit": limit}
    if cursor:
        params["cursor"] = cursor
    if search and search.strip():
        params["search"] = search.strip()
    data = await B2BClient().get_internal_json(
        f"/internal/v1/products?{urlencode(params)}"
    )
    try:
        page = B2BProductPage.model_validate(data)
    except ValidationError as exc:
        raise HTTPException(status_code=502, detail={"code": "B2B_INVALID_PRODUCT_PAGE", "message": "B2B returned an invalid product page"}) from exc
    return ProductPageResponse(
        items=[
            ProductOverview(
                id=item.product_id,
                seller_id=item.seller_id,
                published_revision=item.published_revision,
                current_revision=item.current_revision,
                visible=item.visible,
                visibility_reasons=item.visibility_reasons,
            )
            for item in page.items
        ],
        page=PageResponse(**page.page.model_dump()),
    )


@router.get("/admin/v1/products/{product_id}", response_model=ProductOverview, response_model_exclude_none=True)
async def get_product(
    product_id: UUID,
    actor: SimpleNamespace = Depends(require_permission("products.read")),
    db: AsyncSession = Depends(get_db),
) -> ProductOverview:
    client = B2BClient()
    publication_data = await client.get_internal_json(f"/internal/v1/products/{product_id}/publication")
    try:
        publication = ProductPublication.model_validate(publication_data)
    except ValidationError as exc:
        raise HTTPException(status_code=502, detail={"code": "B2B_INVALID_PUBLICATION", "message": "B2B returned an invalid publication status"}) from exc
    if publication.product_id != product_id:
        raise HTTPException(status_code=502, detail={"code": "B2B_PRODUCT_ID_MISMATCH", "message": "B2B returned a different product"})
    revision_data = await client.get_internal_json(
        f"/internal/v1/products/{product_id}/revisions/{publication.current_revision}"
    )
    try:
        revision = ProductRevisionSnapshot.model_validate(revision_data)
    except ValidationError as exc:
        raise HTTPException(status_code=502, detail={"code": "B2B_INVALID_PRODUCT_REVISION", "message": "B2B returned an invalid product revision"}) from exc
    if revision.product_id != product_id or revision.revision != publication.current_revision:
        raise HTTPException(status_code=502, detail={"code": "B2B_PRODUCT_REVISION_MISMATCH", "message": "B2B returned a different product revision"})
    overview = ProductOverview(
        id=product_id,
        seller_id=revision.seller_id,
        published_revision=publication.published_revision,
        current_revision=publication.current_revision,
        visible=publication.visible,
        visibility_reasons=publication.visibility_reasons,
    )
    db.add(AuditLog(
        actor_id=actor.id,
        action="PRODUCT_READ",
        entity_type="product",
        entity_id=product_id,
        details={"revision": publication.current_revision},
        created_at=datetime.now(timezone.utc),
    ))
    await db.commit()
    return overview


def _operation_response(operation: AdminOperation, request: Request) -> AdminOperationResponse:
    return AdminOperationResponse(
        operation_id=operation.id,
        status=operation.status,
        resource_id=operation.entity_id,
        request_id=getattr(request.state, "request_id", None),
        updated_at=operation.updated_at,
        version=operation.version,
    )


def _recheck_request_hash(product_id: UUID, data: ReasonAction) -> str:
    body = {"product_id": str(product_id), "reason_code": data.reason_code, "comment": data.comment}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _if_match_revision(value: str) -> int:
    try:
        version = int(value.strip().strip('"').removeprefix("v"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "INVALID_IF_MATCH", "message": "If-Match must contain a positive product revision"}) from exc
    if version < 1:
        raise HTTPException(status_code=422, detail={"code": "INVALID_IF_MATCH", "message": "If-Match must contain a positive product revision"})
    return version


def _safety_hold_request_hash(product_id: UUID, data: HoldInput, expected_revision: int) -> str:
    body = {
        "product_id": str(product_id),
        "expected_revision": expected_revision,
        **data.model_dump(mode="json"),
    }
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


@router.post("/admin/v1/products/{product_id}/safety-hold", response_model=AdminOperationResponse, status_code=202, operation_id="POST_admin_v1_products_product_id_safety_hold")
async def request_product_safety_hold(
    product_id: UUID,
    data: HoldInput,
    request: Request,
    if_match: str = Header(alias="If-Match"),
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    actor: SimpleNamespace = Depends(require_permission("products.safety_hold")),
    db: AsyncSession = Depends(get_db),
) -> AdminOperationResponse:
    expected_revision = _if_match_revision(if_match)
    request_hash = _safety_hold_request_hash(product_id, data, expected_revision)
    prior = await db.scalar(select(AdminOperation).where(
        AdminOperation.requested_by == actor.id,
        AdminOperation.idempotency_key == str(idempotency_key),
    ))
    if prior is not None:
        if prior.action != "PRODUCT_SAFETY_HOLD" or not hmac.compare_digest(prior.request_hash, request_hash):
            raise HTTPException(status_code=409, detail={"code": "IDEMPOTENCY_KEY_REUSED", "message": "Idempotency key was used for a different operation"})
        return _operation_response(prior, request)
    if data.expires_at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=422, detail={"code": "INVALID_HOLD_EXPIRY", "message": "Safety hold expiry must be in the future"})
    hold_limit_seconds = settings.admin_safety_hold_max_seconds
    if hold_limit_seconds is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "SAFETY_HOLD_POLICY_NOT_CONFIGURED", "message": "The approved maximum safety-hold duration is not configured"},
        )
    now = datetime.now(timezone.utc)
    hold_duration_seconds = (data.expires_at - now).total_seconds()
    requires_approval = hold_duration_seconds > hold_limit_seconds
    await db.commit()
    publication_data = await B2BClient().get_internal_json(f"/internal/v1/products/{product_id}/publication")
    try:
        publication = ProductPublication.model_validate(publication_data)
    except ValidationError as exc:
        raise HTTPException(status_code=502, detail={"code": "B2B_INVALID_PUBLICATION", "message": "B2B returned an invalid publication status"}) from exc
    if publication.product_id != product_id:
        raise HTTPException(status_code=502, detail={"code": "B2B_PRODUCT_ID_MISMATCH", "message": "B2B returned a different product"})
    if publication.current_revision != expected_revision:
        raise HTTPException(status_code=412, detail={"code": "PRODUCT_REVISION_MISMATCH", "message": "Product changed; reload before applying a safety hold"})
    prior = await db.scalar(select(AdminOperation).where(
        AdminOperation.requested_by == actor.id,
        AdminOperation.idempotency_key == str(idempotency_key),
    ))
    if prior is not None:
        if prior.action != "PRODUCT_SAFETY_HOLD" or not hmac.compare_digest(prior.request_hash, request_hash):
            raise HTTPException(status_code=409, detail={"code": "IDEMPOTENCY_KEY_REUSED", "message": "Idempotency key was used for a different operation"})
        return _operation_response(prior, request)
    operation = AdminOperation(
        id=uuid4(), action="PRODUCT_SAFETY_HOLD", entity_type="product", entity_id=product_id,
        payload={
            "expected_version": expected_revision,
            "command_payload": data.model_dump(mode="json"),
            "hold_limit_seconds": hold_limit_seconds,
        },
        status="WAITING_APPROVAL" if requires_approval else "QUEUED",
        version=1, idempotency_key=str(idempotency_key), request_hash=request_hash,
        requested_by=actor.id, reason_code=data.reason_code, updated_at=datetime.now(timezone.utc),
    )
    command = {
        "command_id": str(operation.id), "command_type": "PRODUCT_SAFETY_HOLD",
        "aggregate_id": str(product_id), "expected_version": expected_revision,
        "payload": data.model_dump(mode="json"), "requested_by_staff_id": str(actor.id),
        "reason_code": data.reason_code, "occurred_at": datetime.now(timezone.utc).isoformat(),
    }
    db.add(operation)
    if not requires_approval:
        db.add(ModerationOutboxEvent(
            idempotency_key=f"admin-command:{operation.id}", event_type="B2B_COMMAND",
            payload={"operation_id": str(operation.id), "entity_type": "product", "command": command},
        ))
    db.add(AuditLog(
        actor_id=actor.id, action="PRODUCT_SAFETY_HOLD_PROPOSED", entity_type="product", entity_id=product_id,
        details={
            "operation_id": str(operation.id), "reason_code": data.reason_code,
            "revision": expected_revision, "expires_at": data.expires_at.isoformat(),
            "hold_limit_seconds": hold_limit_seconds, "maker_checker_required": requires_approval,
        },
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
        if prior is not None and prior.action == "PRODUCT_SAFETY_HOLD" and hmac.compare_digest(prior.request_hash, request_hash):
            return _operation_response(prior, request)
        raise HTTPException(status_code=409, detail={"code": "OPERATION_CONFLICT", "message": "Safety hold could not be recorded"}) from exc
    return _operation_response(operation, request)


async def _current_product_revision(product_id: UUID) -> tuple[ProductRevisionSnapshot, str]:
    client = B2BClient()
    publication_data = await client.get_internal_json(f"/internal/v1/products/{product_id}/publication")
    try:
        publication = ProductPublication.model_validate(publication_data)
    except ValidationError as exc:
        raise HTTPException(status_code=502, detail={"code": "B2B_INVALID_PUBLICATION", "message": "B2B returned an invalid publication status"}) from exc
    if publication.product_id != product_id:
        raise HTTPException(status_code=502, detail={"code": "B2B_PRODUCT_ID_MISMATCH", "message": "B2B returned a different product"})
    revision_data = await client.get_internal_json(
        f"/internal/v1/products/{product_id}/revisions/{publication.current_revision}"
    )
    try:
        revision = ProductRevisionSnapshot.model_validate(revision_data)
        source_hash = normalize_source_digest(revision.snapshot_hash)
    except (ValidationError, ValueError) as exc:
        raise HTTPException(status_code=502, detail={"code": "B2B_INVALID_PRODUCT_REVISION", "message": "B2B returned an invalid product revision snapshot"}) from exc
    if revision.product_id != product_id or revision.revision != publication.current_revision:
        raise HTTPException(status_code=502, detail={"code": "B2B_PRODUCT_REVISION_MISMATCH", "message": "B2B returned a different product revision"})
    if any(not isinstance(item, str) for item in revision.media_refs):
        raise HTTPException(status_code=502, detail={"code": "B2B_INVALID_MEDIA_REFS", "message": "B2B returned invalid media references"})
    return revision, source_hash


@router.post("/admin/v1/products/{product_id}/recheck", response_model=AdminOperationResponse, status_code=202, operation_id="POST_admin_v1_products_product_id_recheck")
async def request_product_recheck(
    product_id: UUID,
    data: ReasonAction,
    request: Request,
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    actor: SimpleNamespace = Depends(require_permission("products.recheck")),
    db: AsyncSession = Depends(get_db),
) -> AdminOperationResponse:
    request_hash = _recheck_request_hash(product_id, data)
    prior = await db.scalar(select(AdminOperation).where(
        AdminOperation.requested_by == actor.id,
        AdminOperation.idempotency_key == str(idempotency_key),
    ))
    if prior is not None:
        if prior.action != "PRODUCT_RECHECK" or not hmac.compare_digest(prior.request_hash, request_hash):
            raise HTTPException(status_code=409, detail={"code": "IDEMPOTENCY_KEY_REUSED", "message": "Idempotency key was used for a different operation"})
        return _operation_response(prior, request)
    # Do not hold a DB transaction open across a service call.
    await db.commit()
    revision, source_hash = await _current_product_revision(product_id)
    local_hash = content_digest(revision.content)
    existing = await db.scalar(select(ModerationCard).where(
        ModerationCard.product_id == product_id,
        ModerationCard.submitted_revision == revision.revision,
        ModerationCard.kind == "RECHECK",
    ))
    if existing is not None:
        raise HTTPException(status_code=409, detail={"code": "RECHECK_ALREADY_EXISTS", "message": "A recheck ticket already exists for the current product revision"})
    # Recheck the idempotency receipt after the network request to cover a
    # concurrent replay while keeping the DB connection out of remote I/O.
    prior = await db.scalar(select(AdminOperation).where(
        AdminOperation.requested_by == actor.id,
        AdminOperation.idempotency_key == str(idempotency_key),
    ))
    if prior is not None:
        if prior.action != "PRODUCT_RECHECK" or not hmac.compare_digest(prior.request_hash, request_hash):
            raise HTTPException(status_code=409, detail={"code": "IDEMPOTENCY_KEY_REUSED", "message": "Idempotency key was used for a different operation"})
        return _operation_response(prior, request)
    now = datetime.now(timezone.utc)
    ticket = ModerationCard(
        product_id=product_id,
        seller_id=revision.seller_id,
        kind="RECHECK",
        queue_priority=4,
        status=ModerationStatus.PENDING,
        submitted_revision=revision.revision,
        snapshot_hash=source_hash,
        version=1,
        fencing_version=0,
    )
    db.add(ticket)
    await db.flush()
    db.add(ModerationSnapshot(
        ticket_id=ticket.id,
        revision=revision.revision,
        policy_version=revision.content.get("policy_version") if type(revision.content.get("policy_version")) is int else None,
        snapshot_hash=source_hash,
        content_hash=local_hash,
        content=revision.content,
        media_refs=revision.media_refs,
    ))
    raw_skus = revision.content.get("skus", [])
    if not isinstance(raw_skus, list):
        raise HTTPException(status_code=502, detail={"code": "B2B_INVALID_PRODUCT_SKUS", "message": "B2B revision contains invalid SKU data"})
    for sku in raw_skus:
        if not isinstance(sku, dict) or not sku.get("id"):
            raise HTTPException(status_code=502, detail={"code": "B2B_INVALID_PRODUCT_SKUS", "message": "B2B revision contains invalid SKU data"})
        try:
            sku_id = UUID(str(sku["id"]))
        except ValueError as exc:
            raise HTTPException(status_code=502, detail={"code": "B2B_INVALID_PRODUCT_SKUS", "message": "B2B revision contains invalid SKU IDs"}) from exc
        db.add(ModerationSKU(card_id=ticket.id, sku_id=sku_id, name=str(sku.get("name") or "")[:255]))
    operation = AdminOperation(
        id=uuid4(),
        action="PRODUCT_RECHECK",
        entity_type="product",
        entity_id=product_id,
        payload={"ticket_id": str(ticket.id), "revision": revision.revision, "snapshot_hash": source_hash},
        status="APPLIED",
        version=1,
        idempotency_key=str(idempotency_key),
        request_hash=request_hash,
        requested_by=actor.id,
        reason_code=data.reason_code,
        updated_at=now,
    )
    db.add(operation)
    db.add(AuditLog(
        actor_id=actor.id,
        action="PRODUCT_RECHECK_CREATED",
        entity_type="product",
        entity_id=product_id,
        details={"ticket_id": str(ticket.id), "revision": revision.revision, "reason_code": data.reason_code},
        created_at=now,
    ))
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        prior = await db.scalar(select(AdminOperation).where(
            AdminOperation.requested_by == actor.id,
            AdminOperation.idempotency_key == str(idempotency_key),
        ))
        if prior is not None and prior.action == "PRODUCT_RECHECK" and hmac.compare_digest(prior.request_hash, request_hash):
            return _operation_response(prior, request)
        existing = await db.scalar(select(ModerationCard).where(
            ModerationCard.product_id == product_id,
            ModerationCard.submitted_revision == revision.revision,
            ModerationCard.kind == "RECHECK",
        ))
        if existing is not None:
            raise HTTPException(status_code=409, detail={"code": "RECHECK_ALREADY_EXISTS", "message": "A recheck ticket already exists for the current product revision"}) from exc
        raise
    return _operation_response(operation, request)
