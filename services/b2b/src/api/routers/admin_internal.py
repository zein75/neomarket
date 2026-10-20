import base64
import binascii
import hashlib
import json
from unicodedata import normalize
from datetime import datetime, timedelta, timezone
from secrets import compare_digest
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from src.api.deps import get_db
from src.core.config import settings
from src.models.category import Category
from src.models.brand import Brand, BrandAlias, BrandMergeHistory, BrandMergePreview
from src.models.attribute_definition import AttributeDefinition
from src.models.product import Product
from src.models.product_version import ProductVersion
from src.models.taxonomy_state import TaxonomyState
from src.models.taxonomy_command_receipt import TaxonomyCommandReceipt
from src.models.taxonomy_impact_preview import TaxonomyImpactPreview
from src.models.taxonomy_impact_job import TaxonomyImpactJob
from src.models.seller import Seller
from src.repositories.product_repo import ProductRepository
from src.repositories.outbox_event_repo import OutboxEventRepository
from src.schemas.admin_internal import (
    AdminBrandResponse,
    AdminProductPageResponse,
    AdminTaxonomyAttributeResponse,
    AdminTaxonomyCategoryResponse,
    AdminTaxonomySnapshotResponse,
    ProductPublicationResponse,
    ProductRevisionSnapshotResponse,
    SafetyHoldPayload,
    ServiceCommandReceiptResponse,
)
from src.schemas.admin_taxonomy import (
    CategoryCreatePayload,
    CategoryMovePayload,
    CategoryRulePayload,
    CategoryRulesPayload,
    CategoryUpdatePayload,
    AttributeDefinitionPayload,
    TaxonomyCommandRequest,
    TaxonomyCommandReceiptResponse,
    TaxonomyImpactPreviewRequest,
    TaxonomyImpactPreviewResponse,
    BrandDefinitionPayload,
    BrandMergePayload,
    BrandMergePreviewRequest,
    BrandMergePreviewResponse,
)
from src.schemas.taxonomy_impact_jobs import TaxonomyImpactJobResponse
from src.services.taxonomy_impact_job_service import TaxonomyImpactJobService
from src.services.product_service import ProductService
from shared.utils.service_auth import verify_service_token

router = APIRouter(prefix="/internal/v1", tags=["admin-internal"])


class AdminSellerView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    seller_id: UUID
    status: str
    reason_code: str | None = None
    version: int = Field(ge=1)
    updated_at: datetime


class AdminSellerPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[AdminSellerView]
    page: dict[str, object]


class SellerRestrictionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["RESTRICT", "SUSPEND", "REINSTATE"]
    reason_code: str = Field(min_length=1, max_length=64, pattern=r"^[A-Z][A-Z0-9_]*$")
    comment: str | None = Field(default=None, max_length=3000)
    effective_until: datetime | None = None


async def verify_admin_service(
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_service_key: str | None = Header(default=None, alias="X-Service-Key"),
) -> None:
    if authorization and authorization.lower().startswith("bearer ") and settings.trusted_service_public_keys:
        if verify_service_token(authorization[7:].strip(), trusted_keys=settings.trusted_service_public_keys, audience="neomarket-b2b", allowed_subjects={"admin"}):
            return
    if settings.app_env.lower() in {"production", "prod"}:
        raise HTTPException(status_code=401, detail={"code": "SERVICE_TOKEN_REQUIRED", "message": "Signed Admin service token is required"})
    if not x_service_key or not compare_digest(x_service_key, settings.service_key):
        raise HTTPException(status_code=401, detail={"code": "SERVICE_KEY_INVALID", "message": "Invalid or missing service key"})


def _seller_view(seller: Seller) -> AdminSellerView:
    return AdminSellerView(
        id=seller.id,
        seller_id=seller.id,
        status=seller.account_status if seller.account_status in {"UNDER_REVIEW", "ACTIVE", "RESTRICTED", "SUSPENDED", "TERMINATED"} else "UNDER_REVIEW",
        version=max(1, seller.session_version),
        updated_at=seller.updated_at,
    )


def _encode_seller_cursor(updated_at: datetime, seller_id: UUID) -> str:
    return base64.urlsafe_b64encode(
        json.dumps([updated_at.isoformat(), str(seller_id)], separators=(",", ":")).encode("utf-8")
    ).decode("ascii")


def _decode_seller_cursor(value: str | None) -> tuple[datetime, UUID] | None:
    if value is None:
        return None
    try:
        if len(value) > 1024:
            raise ValueError("cursor too long")
        raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        payload = json.loads(raw)
        if not isinstance(payload, list) or len(payload) != 2 or not all(isinstance(item, str) for item in payload):
            raise ValueError("invalid cursor payload")
        updated_at = datetime.fromisoformat(payload[0])
        if updated_at.tzinfo is None or updated_at.utcoffset() is None:
            raise ValueError("cursor timestamp must include timezone")
        return updated_at, UUID(payload[1])
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError, OverflowError) as exc:
        raise HTTPException(status_code=422, detail={"code": "INVALID_CURSOR", "message": "Invalid seller pagination cursor"}) from exc


@router.get("/sellers", response_model=AdminSellerPage, operation_id="get__internal_v1_sellers")
async def list_admin_sellers(
    cursor: str | None = Query(default=None, max_length=1024),
    limit: int = Query(default=20, ge=1, le=100),
    _: None = Depends(verify_admin_service),
    db: AsyncSession = Depends(get_db),
) -> AdminSellerPage:
    position = _decode_seller_cursor(cursor)
    query = select(Seller)
    if position is not None:
        updated_at, seller_id = position
        query = query.where(
            (Seller.updated_at < updated_at)
            | ((Seller.updated_at == updated_at) & (Seller.id < seller_id))
        )
    rows = list((await db.scalars(query.order_by(Seller.updated_at.desc(), Seller.id.desc()).limit(limit + 1))).all())
    has_more = len(rows) > limit
    rows = rows[:limit]
    return AdminSellerPage(
        items=[_seller_view(row) for row in rows],
        page={
            "has_more": has_more,
            "next_cursor": _encode_seller_cursor(rows[-1].updated_at, rows[-1].id) if has_more and rows else None,
        },
    )


@router.get("/sellers/{seller_id}", response_model=AdminSellerView, operation_id="get__internal_v1_sellers_seller_id")
async def get_admin_seller(
    seller_id: UUID,
    _: None = Depends(verify_admin_service),
    db: AsyncSession = Depends(get_db),
) -> AdminSellerView:
    seller = await db.get(Seller, seller_id)
    if seller is None:
        raise HTTPException(status_code=404, detail={"code": "SELLER_NOT_FOUND", "message": "Seller not found"})
    return _seller_view(seller)


@router.post("/sellers/{seller_id}/restrictions", response_model=dict, status_code=202, operation_id="post__internal_v1_sellers_seller_id_restrictions")
async def apply_admin_seller_restriction(
    seller_id: UUID,
    command: dict[str, object],
    if_match: str = Header(alias="If-Match"),
    _: None = Depends(verify_admin_service),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    try:
        expected_version = int(if_match.strip().strip('"').removeprefix("v"))
        payload = SellerRestrictionCommand.model_validate(command.get("payload"))
        command_id = UUID(str(command.get("command_id")))
        command_expected_version = int(command.get("expected_version"))
        aggregate_id = UUID(str(command.get("aggregate_id")))
    except (ValueError, TypeError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail={"code": "INVALID_SELLER_COMMAND", "message": "Seller restriction command is invalid"}) from exc
    if (
        expected_version < 1
        or command_expected_version != expected_version
        or aggregate_id != seller_id
        or command.get("command_type") != "SELLER_RESTRICTION"
    ):
        raise HTTPException(status_code=422, detail={"code": "INVALID_SELLER_COMMAND", "message": "Seller restriction command is invalid"})
    payload_hash = hashlib.sha256(json.dumps({"seller_id": str(seller_id), "command": command}, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    prior = await db.get(TaxonomyCommandReceipt, command_id)
    if prior is not None:
        if prior.payload_hash != payload_hash:
            raise HTTPException(status_code=409, detail={"code": "SELLER_COMMAND_ID_CONFLICT", "message": "Command ID was reused with a different seller restriction"})
        return {"command_id": str(prior.command_id), "status": prior.status, "result": prior.result}
    seller = await db.scalar(select(Seller).where(Seller.id == seller_id).with_for_update())
    if seller is None:
        raise HTTPException(status_code=404, detail={"code": "SELLER_NOT_FOUND", "message": "Seller not found"})
    # A concurrent retry can have waited on the seller row lock while the first
    # command committed its receipt. Recheck after the lock so it replays the
    # durable result instead of returning a misleading stale-version error.
    prior = await db.get(TaxonomyCommandReceipt, command_id)
    if prior is not None:
        if prior.payload_hash != payload_hash:
            raise HTTPException(status_code=409, detail={"code": "SELLER_COMMAND_ID_CONFLICT", "message": "Command ID was reused with a different seller restriction"})
        return {"command_id": str(prior.command_id), "status": prior.status, "result": prior.result}
    if seller.session_version != expected_version:
        raise HTTPException(status_code=412, detail={"code": "SELLER_VERSION_MISMATCH", "message": "Seller changed after the restriction was proposed"})
    if payload.action == "REINSTATE":
        seller.account_status = "ACTIVE"
        seller.is_active = True
    elif payload.action == "RESTRICT":
        seller.account_status = "RESTRICTED"
        seller.is_active = False
    else:
        if payload.effective_until is None or payload.effective_until <= datetime.now(timezone.utc):
            raise HTTPException(status_code=422, detail={"code": "INVALID_RESTRICTION_EXPIRY", "message": "Seller suspension must have a future expiry"})
        seller.account_status = "SUSPENDED"
        seller.is_active = False
    seller.session_version += 1
    result = {"seller_id": str(seller.id), "status": seller.account_status, "version": seller.session_version}
    db.add(TaxonomyCommandReceipt(command_id=command_id, payload_hash=payload_hash, status="APPLIED", result=result))
    await db.commit()
    return {
        "command_id": str(command_id),
        "status": "APPLIED",
        "result": result,
    }


@router.post(
    "/products/{product_id}/safety-hold",
    response_model=ServiceCommandReceiptResponse,
    status_code=202,
    operation_id="post__internal_v1_products_product_id_safety_hold",
    openapi_extra={"x-allowed-service": "service:admin"},
)
async def apply_admin_product_safety_hold(
    product_id: UUID,
    command: dict[str, object],
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    if_match: str = Header(alias="If-Match"),
    _: None = Depends(verify_admin_service),
    db: AsyncSession = Depends(get_db),
) -> ServiceCommandReceiptResponse:
    try:
        expected_version = int(if_match.strip().strip('"').removeprefix("v"))
        command_id = UUID(str(command.get("command_id")))
        aggregate_id = UUID(str(command.get("aggregate_id")))
        command_expected_version = int(command.get("expected_version"))
        payload = SafetyHoldPayload.model_validate(command.get("payload"))
        occurred_at = datetime.fromisoformat(str(command.get("occurred_at")))
    except (TypeError, ValueError, ValidationError) as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_PRODUCT_SAFETY_HOLD_COMMAND", "message": "Product safety-hold command is invalid"},
        ) from exc
    if (
        expected_version < 1
        or command_expected_version != expected_version
        or aggregate_id != product_id
        or command.get("command_type") != "PRODUCT_SAFETY_HOLD"
        or occurred_at.tzinfo is None
        or occurred_at.utcoffset() is None
    ):
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_PRODUCT_SAFETY_HOLD_COMMAND", "message": "Product safety-hold command is invalid"},
        )
    now = datetime.now(timezone.utc)
    if payload.expires_at <= now:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_HOLD_EXPIRY", "message": "Safety hold expiry must be in the future"},
        )
    payload_hash = hashlib.sha256(
        json.dumps(
            {"command": command, "idempotency_key": str(idempotency_key)},
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    existing_event = await OutboxEventRepository(db).get_by_idempotency_key(str(idempotency_key))
    expected_event_id = uuid5(NAMESPACE_URL, f"neomarket:product.safety_hold.v1:{command_id}")
    if existing_event is not None and existing_event.event_id != expected_event_id:
        raise HTTPException(
            status_code=409,
            detail={"code": "IDEMPOTENCY_KEY_REUSED", "message": "Idempotency key was used for a different product command"},
        )
    prior = await db.get(TaxonomyCommandReceipt, command_id)
    if prior is not None:
        if prior.payload_hash != payload_hash:
            raise HTTPException(
                status_code=409,
                detail={"code": "PRODUCT_COMMAND_ID_CONFLICT", "message": "Command ID was reused with a different safety hold"},
            )
        result = prior.result or {}
        return ServiceCommandReceiptResponse(
            command_id=prior.command_id,
            status=prior.status,
            aggregate_version=result.get("current_revision"),
            result=result,
        )
    product = await db.scalar(select(Product).where(Product.id == product_id).with_for_update())
    if product is None:
        raise HTTPException(status_code=404, detail={"code": "PRODUCT_NOT_FOUND", "message": "Product not found"})
    prior = await db.get(TaxonomyCommandReceipt, command_id)
    if prior is not None:
        if prior.payload_hash != payload_hash:
            raise HTTPException(status_code=409, detail={"code": "PRODUCT_COMMAND_ID_CONFLICT", "message": "Command ID was reused with a different safety hold"})
        result = prior.result or {}
        return ServiceCommandReceiptResponse(command_id=prior.command_id, status=prior.status, aggregate_version=result.get("current_revision"), result=result)
    if product.revision != expected_version:
        raise HTTPException(status_code=412, detail={"code": "PRODUCT_VERSION_MISMATCH", "message": "Product changed after the safety hold was proposed"})
    current_hold_until = getattr(product, "safety_hold_until", None)
    if current_hold_until is not None and current_hold_until > now:
        raise HTTPException(status_code=409, detail={"code": "SAFETY_HOLD_ALREADY_ACTIVE", "message": "Product already has an active safety hold"})
    product.safety_hold_until = payload.expires_at
    product.safety_hold_reason_code = payload.reason_code
    event_id = expected_event_id
    event = {
        "schema_version": 1,
        "event_id": str(event_id),
        "event_type": "product.safety_hold.v1",
        "producer": "b2b",
        "aggregate_type": "product",
        "aggregate_id": str(product.id),
        "aggregate_version": product.revision,
        "occurred_at": occurred_at.astimezone(timezone.utc).isoformat(),
        "correlation_id": str(command_id),
        "causation_id": str(command_id),
        "payload": {
            "product_id": str(product.id),
            "revision": product.revision,
            "expires_at": payload.expires_at.astimezone(timezone.utc).isoformat(),
            "reason_code": payload.reason_code,
        },
    }
    await OutboxEventRepository(db).create_event(
        destination="B2C",
        idempotency_key=str(idempotency_key),
        event_type="product.safety_hold.v1",
        payload=event,
    )
    result = {
        "product_id": str(product.id),
        "current_revision": product.revision,
        "safety_hold_until": payload.expires_at.astimezone(timezone.utc).isoformat(),
        "reason_code": payload.reason_code,
    }
    db.add(TaxonomyCommandReceipt(command_id=command_id, payload_hash=payload_hash, status="APPLIED", result=result))
    await db.commit()
    return ServiceCommandReceiptResponse(
        command_id=command_id,
        status="APPLIED",
        aggregate_version=product.revision,
        result=result,
    )


def _command_hash(command: TaxonomyCommandRequest) -> str:
    canonical = json.dumps(command.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def _existing_taxonomy_receipt(
    db: AsyncSession, command_id: UUID, payload_hash: str
) -> TaxonomyCommandReceiptResponse | None:
    receipt = await db.get(TaxonomyCommandReceipt, command_id)
    if receipt is None:
        return None
    if receipt.payload_hash != payload_hash:
        raise HTTPException(
            status_code=409,
            detail={"code": "TAXONOMY_COMMAND_ID_CONFLICT", "message": "Command ID was reused with a different payload"},
        )
    return TaxonomyCommandReceiptResponse(command_id=receipt.command_id, status=receipt.status, result=receipt.result)


async def _taxonomy_receipt(
    db: AsyncSession, command: TaxonomyCommandRequest, payload_hash: str,
    status_value: str, result: dict[str, object],
) -> TaxonomyCommandReceiptResponse:
    receipt = TaxonomyCommandReceipt(
        command_id=command.command_id, payload_hash=payload_hash,
        status=status_value, result=result,
    )
    db.add(receipt)
    await db.flush()
    await db.commit()
    return TaxonomyCommandReceiptResponse(command_id=command.command_id, status=status_value, result=result)


def _category_paths(categories: list[Category]) -> dict[UUID, str]:
    by_id = {item.id: item for item in categories}
    paths: dict[UUID, str] = {}
    for category in categories:
        parts: list[str] = []
        current: Category | None = category
        seen: set[UUID] = set()
        while current is not None:
            if current.id in seen:
                raise HTTPException(status_code=503, detail={"code": "CATEGORY_HIERARCHY_INVALID", "message": "Category hierarchy contains a cycle"})
            seen.add(current.id)
            parts.append(current.slug)
            current = by_id.get(current.parent_id) if current.parent_id else None
        paths[category.id] = "/" + "/".join(reversed(parts))
    return paths


@router.post(
    "/taxonomy/categories/{category_id}/impact-preview",
    response_model=TaxonomyImpactPreviewResponse | TaxonomyImpactJobResponse,
    responses={202: {"model": TaxonomyImpactJobResponse}},
    operation_id="post__internal_v1_taxonomy_categories_category_id_impact_preview",
    openapi_extra={"x-allowed-service": "service:admin"},
)
async def preview_taxonomy_impact(
    category_id: UUID,
    data: TaxonomyImpactPreviewRequest,
    response: Response,
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    if_match: str = Header(alias="If-Match"),
    _: None = Depends(verify_admin_service),
    db: AsyncSession = Depends(get_db),
) -> TaxonomyImpactPreviewResponse | TaxonomyImpactJobResponse:
    try:
        expected_version = int(if_match.strip().strip('"').removeprefix("v"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "INVALID_IF_MATCH", "message": "If-Match must contain category version"}) from exc
    request_payload = data.model_dump(mode="json", exclude_none=True)
    request_hash = hashlib.sha256(json.dumps(request_payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    prior = await db.get(TaxonomyImpactPreview, idempotency_key)
    if prior is not None:
        if prior.category_id != category_id or prior.request_hash != request_hash:
            raise HTTPException(status_code=409, detail={"code": "TAXONOMY_PREVIEW_ID_CONFLICT", "message": "Idempotency-Key was reused with a different preview request"})
        if prior.expires_at <= datetime.now(timezone.utc):
            raise HTTPException(status_code=409, detail={"code": "TAXONOMY_PREVIEW_EXPIRED", "message": "Request a fresh impact preview"})
        return TaxonomyImpactPreviewResponse.model_validate(prior.result)
    pending_job = await db.get(TaxonomyImpactJob, idempotency_key)
    if pending_job is not None:
        if pending_job.category_id != category_id or pending_job.request_hash != request_hash:
            raise HTTPException(status_code=409, detail={"code": "TAXONOMY_PREVIEW_ID_CONFLICT", "message": "Idempotency-Key was reused with a different preview request"})
        if pending_job.status in {"QUEUED", "RUNNING"}:
            response.status_code = 202
        return await TaxonomyImpactJobService(db).get_job(pending_job.id)  # type: ignore[return-value]

    state = await db.scalar(select(TaxonomyState).where(TaxonomyState.id == 1).with_for_update())
    if state is None:
        raise HTTPException(status_code=503, detail={"code": "TAXONOMY_NOT_INITIALIZED", "message": "Taxonomy version state is not initialized"})
    category = await db.scalar(select(Category).where(Category.id == category_id).with_for_update())
    if category is None:
        raise HTTPException(status_code=404, detail={"code": "CATEGORY_NOT_FOUND", "message": "Category not found"})
    if category.revision != expected_version:
        raise HTTPException(status_code=412, detail={"code": "CATEGORY_VERSION_MISMATCH", "message": "Category changed; reload before previewing"})
    if data.change_type == "MOVE" and data.new_parent_id is None:
        raise HTTPException(status_code=422, detail={"code": "CATEGORY_PARENT_INVALID", "message": "A new parent is required for a move preview"})
    if data.change_type == "ARCHIVE" and data.new_parent_id is not None:
        raise HTTPException(status_code=422, detail={"code": "INVALID_PREVIEW_REQUEST", "message": "Archive preview cannot include a new parent"})

    proposed_rules: list[dict[str, object]] | None = None
    if data.change_type == "SCHEMA_UPDATE":
        if data.proposed_rules is None:
            raise HTTPException(status_code=422, detail={"code": "SCHEMA_RULES_REQUIRED", "message": "Schema update preview must include proposed rules"})
        try:
            parsed_rules = [CategoryRulePayload.model_validate(rule) for rule in data.proposed_rules]
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail={"code": "INVALID_CATEGORY_RULES", "message": "Schema update preview contains invalid rules"}) from exc
        if any(rule.condition is not None for rule in parsed_rules):
            raise HTTPException(status_code=422, detail={"code": "CONDITIONAL_RULES_UNSUPPORTED", "message": "Conditional rules require an approved evaluator contract"})
        attribute_ids = [rule.attribute_id for rule in parsed_rules]
        if len(attribute_ids) != len(set(attribute_ids)):
            raise HTTPException(status_code=422, detail={"code": "DUPLICATE_ATTRIBUTE_RULE", "message": "Each attribute may appear only once in a category schema"})
        active_ids = set((await db.scalars(
            select(AttributeDefinition.id).where(
                AttributeDefinition.id.in_(set(attribute_ids) or {UUID(int=0)}),
                AttributeDefinition.status == "ACTIVE",
            )
        )).all())
        if active_ids != set(attribute_ids):
            raise HTTPException(status_code=422, detail={"code": "ATTRIBUTE_NOT_FOUND", "message": "A schema rule references an unavailable attribute"})
        proposed_rules = [rule.model_dump(mode="json") for rule in parsed_rules]

    # The singleton taxonomy lock serializes preview creation and commands. Recheck
    # the idempotency key after acquiring it to make concurrent replay deterministic.
    prior = await db.get(TaxonomyImpactPreview, idempotency_key)
    if prior is not None:
        if prior.category_id != category_id or prior.request_hash != request_hash:
            raise HTTPException(status_code=409, detail={"code": "TAXONOMY_PREVIEW_ID_CONFLICT", "message": "Idempotency-Key was reused with a different preview request"})
        return TaxonomyImpactPreviewResponse.model_validate(prior.result)
    pending_job = await db.get(TaxonomyImpactJob, idempotency_key)
    if pending_job is not None:
        if pending_job.category_id != category_id or pending_job.request_hash != request_hash:
            raise HTTPException(status_code=409, detail={"code": "TAXONOMY_PREVIEW_ID_CONFLICT", "message": "Idempotency-Key was reused with a different preview request"})
        if pending_job.status in {"QUEUED", "RUNNING"}:
            response.status_code = 202
        return await TaxonomyImpactJobService(db).get_job(pending_job.id)  # type: ignore[return-value]

    subtree = TaxonomyImpactJobService._descendants(category_id)
    descendant_count = int(await db.scalar(select(func.count()).select_from(subtree)) or 0)
    product_count = int(await db.scalar(
        select(func.count(Product.id)).where(
            Product.category_id.in_(select(subtree.c.id)), Product.deleted.is_(False)
        )
    ) or 0)
    if data.change_type == "MOVE":
        parent = await db.get(Category, data.new_parent_id)
        if parent is None or parent.status not in {"DRAFT", "ACTIVE"}:
            raise HTTPException(status_code=422, detail={"code": "CATEGORY_PARENT_INVALID", "message": "New parent must exist and be active or draft"})
        if await db.scalar(select(Category.id).where(Category.id == data.new_parent_id, Category.id.in_(select(subtree.c.id)))) is not None:
            raise HTTPException(status_code=409, detail={"code": "CATEGORY_MOVE_CYCLE", "message": "A category cannot be moved into its descendant"})
    if descendant_count > 5000 or product_count > 5000:
        job = TaxonomyImpactJob(
            id=idempotency_key,
            category_id=category_id,
            change_type=data.change_type,
            request_hash=request_hash,
            taxonomy_version=state.version,
            category_version=category.revision,
            request=request_payload,
            status="QUEUED",
            total_categories=descendant_count,
            total_products=product_count,
            source_product_count=int(await db.scalar(select(func.count(Product.id))) or 0),
            products_updated_at=await db.scalar(select(func.max(Product.updated_at))),
        )
        db.add(job)
        try:
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            existing_job = await db.get(TaxonomyImpactJob, idempotency_key)
            if existing_job is None or existing_job.request_hash != request_hash or existing_job.category_id != category_id:
                raise HTTPException(status_code=409, detail={"code": "TAXONOMY_PREVIEW_ID_CONFLICT", "message": "Impact preview job was created concurrently with a different request"}) from exc
            if existing_job.status in {"QUEUED", "RUNNING"}:
                response.status_code = 202
            return await TaxonomyImpactJobService(db).get_job(existing_job.id)  # type: ignore[return-value]
        response.status_code = 202
        return await TaxonomyImpactJobService(db).get_job(job.id)  # type: ignore[return-value]

    categories = list((await db.scalars(select(Category).order_by(Category.id))).all())
    by_id = {item.id: item for item in categories}
    descendants: set[UUID] = {category.id}
    changed = True
    while changed:
        changed = False
        for item in categories:
            if item.parent_id in descendants and item.id not in descendants:
                descendants.add(item.id)
                changed = True
    old_paths = _category_paths(categories)
    warnings: list[str] = []
    if data.change_type == "MOVE":
        parent = by_id.get(data.new_parent_id)
        if parent is None or parent.status not in {"DRAFT", "ACTIVE"}:
            raise HTTPException(status_code=422, detail={"code": "CATEGORY_PARENT_INVALID", "message": "New parent must exist and be active or draft"})
        if data.new_parent_id in descendants:
            raise HTTPException(status_code=409, detail={"code": "CATEGORY_MOVE_CYCLE", "message": "A category cannot be moved into its descendant"})
    else:
        child_count = len(descendants) - 1
        product_count = int(await db.scalar(select(func.count(Product.id)).where(Product.category_id == category_id, Product.deleted.is_(False))) or 0)
        if child_count:
            warnings.append("CATEGORY_HAS_CHILDREN")
        if product_count:
            warnings.append("CATEGORY_HAS_PRODUCTS")

    products = list((await db.scalars(select(Product).where(Product.category_id.in_(descendants), Product.deleted.is_(False)))).all())
    invalid_products = 0
    requires_reapproval = 0
    if data.change_type in {"MOVE", "SCHEMA_UPDATE"}:
        original_parent_id = category.parent_id
        original_schema_version = category.schema_version
        original_attribute_rules = category.attribute_rules
        if data.change_type == "MOVE":
            category.parent_id = data.new_parent_id
        else:
            category.schema_version = original_schema_version + 1
            category.attribute_rules = proposed_rules or []
        service = ProductService(db)
        try:
            with db.no_autoflush:
                for product in products:
                    product_category = by_id.get(product.category_id)
                    if product_category is None:
                        continue
                    try:
                        await service._validate_category_attributes(product_category, product.characteristics or {})
                    except HTTPException as exc:
                        if exc.status_code == 422:
                            invalid_products += 1
                            if product.published_revision is not None:
                                requires_reapproval += 1
                        else:
                            raise HTTPException(status_code=503, detail={"code": "TAXONOMY_IMPACT_VALIDATION_UNAVAILABLE", "message": "Current product schemas could not be validated"}) from exc
        finally:
            category.parent_id = original_parent_id
            category.schema_version = original_schema_version
            category.attribute_rules = original_attribute_rules
    new_paths = old_paths
    if data.change_type == "MOVE":
        original_parent_id = category.parent_id
        category.parent_id = data.new_parent_id
        try:
            new_paths = _category_paths(categories)
        finally:
            category.parent_id = original_parent_id
    redirects = [
        {"old_path": old_paths[item_id], "new_path": new_paths[item_id]}
        for item_id in descendants
        if old_paths[item_id] != new_paths[item_id]
    ]
    redirects.sort(key=lambda item: (item["old_path"].count("/"), item["old_path"]))
    published_count = sum(1 for product in products if product.published_revision is not None)
    affected_sellers = len({product.seller_id for product in products})
    if data.change_type == "MOVE" and published_count:
        warnings.append("SEARCH_AND_FILTER_INDEX_REBUILD_REQUIRED")
    if data.change_type == "SCHEMA_UPDATE" and invalid_products:
        warnings.append("SCHEMA_MIGRATION_POLICY_REQUIRED")
    if data.change_type == "SCHEMA_UPDATE" and published_count:
        warnings.append("SEARCH_AND_FILTER_INDEX_REBUILD_REQUIRED")
    hash_payload = {
        "category_id": str(category_id), "change_type": data.change_type,
        "taxonomy_version": state.version, "category_version": category.revision,
        "request": request_payload, "affected_products": len(products),
        "affected_sellers": affected_sellers,
        "affected_categories": len(descendants), "invalid_products": invalid_products,
        "requires_reapproval": requires_reapproval, "redirects": redirects, "warnings": warnings,
    }
    impact_hash = hashlib.sha256(json.dumps(hash_payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    result = TaxonomyImpactPreviewResponse(
        change_id=idempotency_key, affected_products=len(products), affected_sellers=affected_sellers,
        affected_categories=len(descendants),
        invalid_products=invalid_products, requires_reapproval=requires_reapproval,
        redirects=redirects, warnings=warnings, hash=impact_hash,
    )
    db.add(TaxonomyImpactPreview(
        id=idempotency_key, category_id=category_id, change_type=data.change_type,
        request_hash=request_hash, impact_hash=impact_hash, taxonomy_version=state.version,
        category_version=category.revision, request=request_payload,
        result=result.model_dump(mode="json"), expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
    ))
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail={"code": "TAXONOMY_PREVIEW_ID_CONFLICT", "message": "Preview was created concurrently; retry with a new Idempotency-Key"}) from exc
    return result


@router.get(
    "/taxonomy/impact-preview-jobs/{job_id}",
    response_model=TaxonomyImpactJobResponse,
    operation_id="get__internal_v1_taxonomy_impact_preview_jobs_job_id",
    openapi_extra={"x-allowed-service": "service:admin"},
)
async def get_taxonomy_impact_job(
    job_id: UUID,
    _: None = Depends(verify_admin_service),
    db: AsyncSession = Depends(get_db),
) -> TaxonomyImpactJobResponse:
    job = await TaxonomyImpactJobService(db).get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail={"code": "TAXONOMY_IMPACT_JOB_NOT_FOUND", "message": "Impact preview job not found"})
    return job


@router.post(
    "/taxonomy/brands/{brand_id}/merge-preview",
    response_model=BrandMergePreviewResponse,
    operation_id="post__internal_v1_taxonomy_brands_brand_id_merge_preview",
    openapi_extra={"x-allowed-service": "service:admin"},
)
async def preview_brand_merge(
    brand_id: UUID,
    data: BrandMergePreviewRequest,
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    if_match: str = Header(alias="If-Match"),
    _: None = Depends(verify_admin_service),
    db: AsyncSession = Depends(get_db),
) -> BrandMergePreviewResponse:
    try:
        expected_version = int(if_match.strip().strip('"').removeprefix("v"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "INVALID_IF_MATCH", "message": "If-Match must contain source brand version"}) from exc
    request_data = data.model_dump(mode="json")
    request_hash = hashlib.sha256(json.dumps(request_data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    prior = await db.get(BrandMergePreview, idempotency_key)
    if prior is not None:
        if prior.source_brand_id != brand_id or prior.request_hash != request_hash:
            raise HTTPException(status_code=409, detail={"code": "BRAND_PREVIEW_ID_CONFLICT", "message": "Idempotency-Key was reused with a different brand preview request"})
        if prior.expires_at <= datetime.now(timezone.utc):
            raise HTTPException(status_code=409, detail={"code": "BRAND_PREVIEW_EXPIRED", "message": "Request a fresh brand merge preview"})
        return BrandMergePreviewResponse(
            change_id=prior.id, source_brand_id=prior.source_brand_id, target_brand_id=prior.target_brand_id,
            affected_products=prior.product_count, hash=prior.impact_hash, expires_at=prior.expires_at,
        )
    state = await db.scalar(select(TaxonomyState).where(TaxonomyState.id == 1).with_for_update())
    if state is None:
        raise HTTPException(status_code=503, detail={"code": "TAXONOMY_NOT_INITIALIZED", "message": "Taxonomy version state is not initialized"})
    source = await db.scalar(select(Brand).where(Brand.id == brand_id).with_for_update())
    target = await db.scalar(select(Brand).where(Brand.id == data.target_brand_id).with_for_update())
    if source is None or target is None:
        raise HTTPException(status_code=404, detail={"code": "BRAND_NOT_FOUND", "message": "Source or target brand not found"})
    if source.id == target.id:
        raise HTTPException(status_code=422, detail={"code": "BRAND_MERGE_SELF", "message": "A brand cannot be merged into itself"})
    if source.version != expected_version:
        raise HTTPException(status_code=412, detail={"code": "BRAND_VERSION_MISMATCH", "message": "Source brand changed; reload before previewing"})
    if source.status == "MERGED" or source.merged_into_id is not None:
        raise HTTPException(status_code=409, detail={"code": "BRAND_ALREADY_MERGED", "message": "Merged brands cannot be merged again"})
    if target.status != "VERIFIED" or target.merged_into_id is not None:
        raise HTTPException(status_code=409, detail={"code": "BRAND_TARGET_NOT_VERIFIED", "message": "Target brand must be verified and canonical"})
    product_count = int(await db.scalar(select(func.count(Product.id)).where(Product.brand_id == source.id)) or 0)
    impact_payload = {
        "source_brand_id": str(source.id), "target_brand_id": str(target.id),
        "source_version": source.version, "target_version": target.version,
        "taxonomy_version": state.version, "product_count": product_count,
    }
    impact_hash = hashlib.sha256(json.dumps(impact_payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)
    preview = BrandMergePreview(
        id=idempotency_key, source_brand_id=source.id, target_brand_id=target.id,
        source_version=source.version, target_version=target.version, taxonomy_version=state.version,
        product_count=product_count, impact_hash=impact_hash, request_hash=request_hash,
        expires_at=expires_at,
    )
    db.add(preview)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail={"code": "BRAND_PREVIEW_ID_CONFLICT", "message": "Preview was created concurrently; retry with a fresh key"}) from exc
    return BrandMergePreviewResponse(
        change_id=idempotency_key, source_brand_id=source.id, target_brand_id=target.id,
        affected_products=product_count, hash=impact_hash, expires_at=expires_at,
    )


@router.post(
    "/taxonomy/commands",
    response_model=TaxonomyCommandReceiptResponse,
    operation_id="post__internal_v1_taxonomy_commands",
    openapi_extra={"x-allowed-service": "service:admin"},
)
async def apply_taxonomy_command(
    command: TaxonomyCommandRequest,
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    if_match: str = Header(alias="If-Match"),
    _: None = Depends(verify_admin_service),
    db: AsyncSession = Depends(get_db),
) -> TaxonomyCommandReceiptResponse:
    if idempotency_key != command.command_id:
        raise HTTPException(status_code=422, detail={"code": "IDEMPOTENCY_KEY_MISMATCH", "message": "Idempotency-Key must equal command_id"})
    try:
        header_version = int(if_match.strip().strip('"').removeprefix("v"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "INVALID_IF_MATCH", "message": "If-Match must contain expected_version"}) from exc
    if header_version != command.expected_version:
        raise HTTPException(status_code=412, detail={"code": "VERSION_HEADER_MISMATCH", "message": "If-Match must equal expected_version"})
    payload_hash = _command_hash(command)
    existing = await _existing_taxonomy_receipt(db, command.command_id, payload_hash)
    if existing is not None:
        return existing

    state = await db.scalar(select(TaxonomyState).where(TaxonomyState.id == 1).with_for_update())
    if state is None:
        raise HTTPException(status_code=503, detail={"code": "TAXONOMY_NOT_INITIALIZED", "message": "Taxonomy version state is not initialized"})
    # A concurrent retry may have passed the initial read before it waited for
    # the taxonomy singleton lock. Recheck while serialized to prevent reapply.
    existing = await _existing_taxonomy_receipt(db, command.command_id, payload_hash)
    if existing is not None:
        return existing

    impact_preview: TaxonomyImpactPreview | None = None
    if command.command_type in {"CATEGORY_MOVE", "CATEGORY_ARCHIVE", "ATTRIBUTE_RULES_PUBLISH"}:
        payload_hash_value = command.payload.get("impact_hash")
        if not command.impact_hash or payload_hash_value != command.impact_hash:
            return await _taxonomy_receipt(db, command, payload_hash, "REJECTED", {"code": "TAXONOMY_IMPACT_PREVIEW_REQUIRED"})
        impact_preview = await db.scalar(
            select(TaxonomyImpactPreview).where(
                TaxonomyImpactPreview.impact_hash == command.impact_hash
            ).with_for_update()
        )
        if impact_preview is None:
            return await _taxonomy_receipt(db, command, payload_hash, "REJECTED", {"code": "TAXONOMY_IMPACT_PREVIEW_NOT_FOUND"})
        expected_change_type = {
            "CATEGORY_MOVE": "MOVE",
            "CATEGORY_ARCHIVE": "ARCHIVE",
            "ATTRIBUTE_RULES_PUBLISH": "SCHEMA_UPDATE",
        }[command.command_type]
        if (
            impact_preview.category_id != command.aggregate_id
            or impact_preview.change_type != expected_change_type
            or impact_preview.taxonomy_version != state.version
            or impact_preview.category_version != command.expected_version
            or impact_preview.expires_at <= datetime.now(timezone.utc)
            or (
                expected_change_type == "MOVE"
                and str(impact_preview.request.get("new_parent_id")) != str(command.payload.get("new_parent_id"))
            )
            or (
                expected_change_type == "SCHEMA_UPDATE"
                and json.dumps(impact_preview.request.get("proposed_rules"), sort_keys=True, separators=(",", ":"))
                != json.dumps(command.payload.get("rules"), sort_keys=True, separators=(",", ":"))
            )
        ):
            return await _taxonomy_receipt(db, command, payload_hash, "CONFLICT", {"code": "TAXONOMY_IMPACT_PREVIEW_STALE"})
        if impact_preview.consumed_by_command_id not in {None, command.command_id}:
            return await _taxonomy_receipt(db, command, payload_hash, "REJECTED", {"code": "TAXONOMY_IMPACT_PREVIEW_CONSUMED"})
        if expected_change_type in {"MOVE", "SCHEMA_UPDATE"} and int(impact_preview.result.get("invalid_products", 0)) > 0:
            return await _taxonomy_receipt(db, command, payload_hash, "REJECTED", {"code": "SCHEMA_MIGRATION_POLICY_UNCONFIGURED", "invalid_products": int(impact_preview.result["invalid_products"])})
        if expected_change_type == "SCHEMA_UPDATE" and "SEARCH_AND_FILTER_INDEX_REBUILD_REQUIRED" in set(impact_preview.result.get("warnings", [])):
            return await _taxonomy_receipt(db, command, payload_hash, "REJECTED", {"code": "SEARCH_INDEX_CONTRACT_UNCONFIGURED"})

    category_commands = {
        "CATEGORY_CREATE", "CATEGORY_UPDATE", "CATEGORY_MOVE",
        "CATEGORY_ARCHIVE", "CATEGORY_PUBLISH", "ATTRIBUTE_RULES_PUBLISH",
        "ATTRIBUTE_CREATE", "ATTRIBUTE_UPDATE", "BRAND_CREATE", "BRAND_UPDATE",
        "BRAND_VERIFY", "BRAND_MERGE",
    }
    if command.command_type not in category_commands:
        return await _taxonomy_receipt(db, command, payload_hash, "REJECTED", {"code": "COMMAND_NOT_CONFIGURED"})

    if command.command_type in {"ATTRIBUTE_CREATE", "ATTRIBUTE_UPDATE"}:
        attribute = None
        if command.command_type == "ATTRIBUTE_UPDATE":
            attribute = await db.scalar(
                select(AttributeDefinition).where(AttributeDefinition.id == command.aggregate_id).with_for_update()
            )
            if attribute is None:
                return await _taxonomy_receipt(db, command, payload_hash, "REJECTED", {"code": "ATTRIBUTE_NOT_FOUND"})
            if attribute.version != command.expected_version:
                return await _taxonomy_receipt(db, command, payload_hash, "CONFLICT", {"code": "ATTRIBUTE_VERSION_MISMATCH", "current_version": attribute.version})
        elif command.expected_version != state.version:
            return await _taxonomy_receipt(db, command, payload_hash, "CONFLICT", {"code": "TAXONOMY_VERSION_MISMATCH", "current_version": state.version})

        attribute_payload = command.payload.get("attribute")
        try:
            definition = AttributeDefinitionPayload.model_validate(attribute_payload)
        except ValidationError:
            return await _taxonomy_receipt(db, command, payload_hash, "REJECTED", {"code": "INVALID_ATTRIBUTE_DEFINITION"})
        if command.payload.get("draft_action") != ("CREATE" if attribute is None else "UPDATE"):
            return await _taxonomy_receipt(db, command, payload_hash, "REJECTED", {"code": "INVALID_ATTRIBUTE_ACTION"})
        values = definition.model_dump(mode="python")
        if attribute is None:
            attribute = AttributeDefinition(id=command.aggregate_id, **values, status="ACTIVE", version=1)
            db.add(attribute)
        else:
            if attribute.status != "ACTIVE":
                return await _taxonomy_receipt(db, command, payload_hash, "REJECTED", {"code": "ATTRIBUTE_NOT_ACTIVE"})
            for key, value in values.items():
                setattr(attribute, key, value)
            attribute.version += 1
        state.version += 1
        try:
            await db.flush()
            receipt = await _taxonomy_receipt(
                db, command, payload_hash, "APPLIED",
                {"aggregate_id": str(attribute.id), "aggregate_version": attribute.version, "taxonomy_version": state.version},
            )
        except IntegrityError:
            await db.rollback()
            existing = await _existing_taxonomy_receipt(db, command.command_id, payload_hash)
            if existing is not None:
                return existing
            return await _taxonomy_receipt(db, command, payload_hash, "REJECTED", {"code": "ATTRIBUTE_CODE_EXISTS"})
        return receipt

    if command.command_type in {"BRAND_CREATE", "BRAND_UPDATE", "BRAND_VERIFY", "BRAND_MERGE"}:
        brand = None if command.command_type == "BRAND_CREATE" else await db.scalar(
            select(Brand).where(Brand.id == command.aggregate_id).with_for_update()
        )
        if command.command_type == "BRAND_CREATE":
            if command.expected_version != state.version:
                return await _taxonomy_receipt(db, command, payload_hash, "CONFLICT", {"code": "TAXONOMY_VERSION_MISMATCH", "current_version": state.version})
        else:
            if brand is None:
                return await _taxonomy_receipt(db, command, payload_hash, "REJECTED", {"code": "BRAND_NOT_FOUND"})
            if brand.version != command.expected_version:
                return await _taxonomy_receipt(db, command, payload_hash, "CONFLICT", {"code": "BRAND_VERSION_MISMATCH", "current_version": brand.version})

        if command.command_type in {"BRAND_CREATE", "BRAND_UPDATE"}:
            try:
                definition = BrandDefinitionPayload.model_validate(command.payload.get("brand"))
            except ValidationError:
                return await _taxonomy_receipt(db, command, payload_hash, "REJECTED", {"code": "INVALID_BRAND"})
            normalized_name = normalize("NFKC", definition.name).casefold()
            name_owner = await db.scalar(select(Brand.id).where(Brand.normalized_name == normalized_name, Brand.id != (brand.id if brand else UUID(int=0))))
            if name_owner is not None:
                return await _taxonomy_receipt(db, command, payload_hash, "REJECTED", {"code": "BRAND_NAME_EXISTS"})
            alias_values = [(normalize("NFKC", alias).casefold(), alias) for alias in definition.aliases]
            for normalized_alias, _ in alias_values:
                if normalized_alias == normalized_name:
                    return await _taxonomy_receipt(db, command, payload_hash, "REJECTED", {"code": "BRAND_ALIAS_CONFLICT"})
                alias_owner = await db.scalar(select(BrandAlias.brand_id).where(BrandAlias.normalized_alias == normalized_alias))
                alias_name_owner = await db.scalar(select(Brand.id).where(Brand.normalized_name == normalized_alias))
                if (alias_owner is not None and (brand is None or alias_owner != brand.id)) or (alias_name_owner is not None and (brand is None or alias_name_owner != brand.id)):
                    return await _taxonomy_receipt(db, command, payload_hash, "REJECTED", {"code": "BRAND_ALIAS_CONFLICT"})
            if command.payload.get("draft_action") != ("CREATE" if brand is None else "UPDATE"):
                return await _taxonomy_receipt(db, command, payload_hash, "REJECTED", {"code": "INVALID_BRAND_ACTION"})
            if brand is None:
                brand = Brand(
                    id=command.aggregate_id, name=definition.name, normalized_name=normalized_name,
                    status="DRAFT", evidence_ref=definition.evidence_ref, version=1,
                )
                db.add(brand)
            else:
                if brand.status in {"RESTRICTED", "MERGED"}:
                    return await _taxonomy_receipt(db, command, payload_hash, "REJECTED", {"code": "BRAND_NOT_EDITABLE"})
                brand.name = definition.name
                brand.normalized_name = normalized_name
                brand.evidence_ref = definition.evidence_ref
                brand.status = "DRAFT"  # edits invalidate any previous verification
                brand.version += 1
                await db.execute(BrandAlias.__table__.delete().where(BrandAlias.brand_id == brand.id))
            db.add_all([
                BrandAlias(brand_id=brand.id, alias=alias, normalized_alias=normalized_alias)
                for normalized_alias, alias in alias_values
            ])
        elif command.command_type == "BRAND_VERIFY":
            evidence_ref = command.payload.get("evidence_ref")
            if brand.status != "DRAFT" or not isinstance(evidence_ref, str) or not evidence_ref.strip() or evidence_ref != brand.evidence_ref:
                return await _taxonomy_receipt(db, command, payload_hash, "REJECTED", {"code": "BRAND_EVIDENCE_REQUIRED"})
            brand.status = "VERIFIED"
            brand.version += 1
        else:
            try:
                merge = BrandMergePayload.model_validate(command.payload)
            except ValidationError:
                return await _taxonomy_receipt(db, command, payload_hash, "REJECTED", {"code": "INVALID_BRAND_MERGE"})
            if merge.reason_code != command.reason_code:
                return await _taxonomy_receipt(db, command, payload_hash, "REJECTED", {"code": "BRAND_REASON_CODE_MISMATCH"})
            if command.impact_hash != merge.impact_hash:
                return await _taxonomy_receipt(db, command, payload_hash, "REJECTED", {"code": "BRAND_IMPACT_PREVIEW_REQUIRED"})
            preview = await db.scalar(select(BrandMergePreview).where(BrandMergePreview.impact_hash == merge.impact_hash).with_for_update())
            target = await db.scalar(select(Brand).where(Brand.id == merge.target_brand_id).with_for_update())
            if preview is None or target is None:
                return await _taxonomy_receipt(db, command, payload_hash, "REJECTED", {"code": "BRAND_MERGE_PREVIEW_NOT_FOUND"})
            current_product_count = int(await db.scalar(select(func.count(Product.id)).where(Product.brand_id == brand.id)) or 0)
            if (
                preview.source_brand_id != brand.id or preview.target_brand_id != target.id
                or preview.source_version != brand.version or preview.target_version != target.version
                or preview.taxonomy_version != state.version or preview.expires_at <= datetime.now(timezone.utc)
                or preview.product_count != current_product_count
            ):
                return await _taxonomy_receipt(db, command, payload_hash, "CONFLICT", {"code": "BRAND_MERGE_PREVIEW_STALE"})
            if target.status != "VERIFIED" or brand.status == "MERGED" or brand.id == target.id:
                return await _taxonomy_receipt(db, command, payload_hash, "REJECTED", {"code": "BRAND_MERGE_STATE_INVALID"})
            source_aliases = list((await db.scalars(select(BrandAlias).where(BrandAlias.brand_id == brand.id).with_for_update())).all())
            target_aliases = list((await db.scalars(select(BrandAlias).where(BrandAlias.brand_id == target.id).with_for_update())).all())
            existing_target_aliases = {row.normalized_alias for row in target_aliases}
            additions = [(brand.normalized_name, brand.name)] + [(row.normalized_alias, row.alias) for row in source_aliases]
            for normalized_alias, _ in additions:
                owner = await db.scalar(select(Brand.id).where(Brand.normalized_name == normalized_alias, Brand.id.not_in({brand.id, target.id})))
                alias_owner = await db.scalar(select(BrandAlias.brand_id).where(BrandAlias.normalized_alias == normalized_alias, BrandAlias.brand_id.not_in({brand.id, target.id})))
                if owner is not None or alias_owner is not None:
                    return await _taxonomy_receipt(db, command, payload_hash, "REJECTED", {"code": "BRAND_ALIAS_CONFLICT"})
            for normalized_alias, alias in additions:
                if normalized_alias != target.normalized_name and normalized_alias not in existing_target_aliases:
                    db.add(BrandAlias(brand_id=target.id, alias=alias, normalized_alias=normalized_alias))
                    existing_target_aliases.add(normalized_alias)
            moved = await db.execute(update(Product).where(Product.brand_id == brand.id).values(brand_id=target.id))
            moved_count = int(moved.rowcount or 0)
            previous_source_version = brand.version
            previous_target_version = target.version
            brand.status = "MERGED"
            brand.merged_into_id = target.id
            brand.version += 1
            target.version += 1
            preview.consumed_by_command_id = command.command_id
            db.add(BrandMergeHistory(
                command_id=command.command_id, source_brand_id=brand.id, target_brand_id=target.id,
                source_version=previous_source_version, target_version=previous_target_version,
                product_references_moved=moved_count, impact_hash=merge.impact_hash,
                reason_code=command.reason_code, approved_by_staff_id=command.approved_by_staff_id,
                occurred_at=command.occurred_at,
            ))
        state.version += 1
        if command.command_type == "BRAND_MERGE":
            event_id = uuid5(NAMESPACE_URL, f"neomarket:brand.merged.v1:{command.command_id}")
            event = {
                "schema_version": 1,
                "event_id": str(event_id),
                "event_type": "brand.merged.v1",
                "producer": "b2b",
                "aggregate_type": "brand",
                "aggregate_id": str(brand.id),
                "aggregate_version": brand.version,
                "occurred_at": command.occurred_at.astimezone(timezone.utc).isoformat(),
                "correlation_id": str(command.command_id),
                "causation_id": str(command.command_id),
                "payload": {
                    "source_brand_id": str(brand.id),
                    "target_brand_id": str(target.id),
                    "source_version": brand.version,
                    "target_version": target.version,
                    "taxonomy_version": state.version,
                    "product_references_moved": moved_count,
                    "impact_hash": merge.impact_hash,
                },
            }
            await OutboxEventRepository(db).create_event(
                destination="B2C",
                idempotency_key=f"brand-merged:{command.command_id}",
                event_type="brand.merged.v1",
                payload=event,
            )
        try:
            await db.flush()
            result = {"aggregate_id": str(command.aggregate_id), "aggregate_version": brand.version, "taxonomy_version": state.version}
            if command.command_type == "BRAND_MERGE":
                result["target_brand_id"] = str(merge.target_brand_id)
                result["product_references_moved"] = moved_count
            return await _taxonomy_receipt(db, command, payload_hash, "APPLIED", result)
        except IntegrityError:
            await db.rollback()
            existing = await _existing_taxonomy_receipt(db, command.command_id, payload_hash)
            if existing is not None:
                return existing
            return await _taxonomy_receipt(db, command, payload_hash, "REJECTED", {"code": "BRAND_NAME_OR_ALIAS_EXISTS"})

    category = await db.scalar(
        select(Category).where(Category.id == command.aggregate_id).with_for_update()
    ) if command.command_type != "CATEGORY_CREATE" else None

    if command.command_type == "CATEGORY_CREATE":
        if command.expected_version != state.version:
            return await _taxonomy_receipt(db, command, payload_hash, "CONFLICT", {"code": "TAXONOMY_VERSION_MISMATCH", "current_version": state.version})
        try:
            create_data = CategoryCreatePayload.model_validate(command.payload)
        except ValidationError:
            return await _taxonomy_receipt(db, command, payload_hash, "REJECTED", {"code": "INVALID_CATEGORY"})
        data = create_data.model_dump(mode="python")
        parent_id = create_data.parent_id
        if parent_id is not None:
            parent = await db.scalar(select(Category).where(Category.id == parent_id).with_for_update())
            if parent is None or parent.status not in {"DRAFT", "ACTIVE"}:
                return await _taxonomy_receipt(db, command, payload_hash, "REJECTED", {"code": "CATEGORY_PARENT_INVALID"})
        category = Category(
            id=command.aggregate_id,
            code=data["code"], slug=data["slug"], name=data["name"],
            labels=data["labels"],
            description=data.get("description"), parent_id=parent_id,
            status="DRAFT", is_active=False, sort_order=data.get("sort_order"),
            seo_title=data.get("seo_title"), image_media_id=data.get("image_media_id"),
            revision=1,
        )
        db.add(category)
    else:
        if category is None:
            return await _taxonomy_receipt(db, command, payload_hash, "REJECTED", {"code": "CATEGORY_NOT_FOUND"})
        if category.revision != command.expected_version:
            return await _taxonomy_receipt(db, command, payload_hash, "CONFLICT", {"code": "CATEGORY_VERSION_MISMATCH", "current_version": category.revision})
        if category.status == "ARCHIVED" and command.command_type not in {"CATEGORY_PUBLISH"}:
            return await _taxonomy_receipt(db, command, payload_hash, "REJECTED", {"code": "CATEGORY_ARCHIVED"})
        data = command.payload
        if command.command_type == "CATEGORY_UPDATE":
            try:
                update_data = CategoryUpdatePayload.model_validate(data).model_dump(mode="python", exclude_unset=True)
            except ValidationError:
                return await _taxonomy_receipt(db, command, payload_hash, "REJECTED", {"code": "INVALID_CATEGORY"})
            for key, value in update_data.items():
                setattr(category, key, value)
        elif command.command_type == "CATEGORY_MOVE":
            try:
                move_data = CategoryMovePayload.model_validate(data)
            except ValidationError:
                return await _taxonomy_receipt(db, command, payload_hash, "REJECTED", {"code": "CATEGORY_PARENT_INVALID"})
            parent_uuid = move_data.new_parent_id
            if parent_uuid == category.id:
                return await _taxonomy_receipt(db, command, payload_hash, "REJECTED", {"code": "CATEGORY_MOVE_CYCLE"})
            parent = await db.scalar(select(Category).where(Category.id == parent_uuid).with_for_update())
            if parent is None or parent.status not in {"DRAFT", "ACTIVE"}:
                return await _taxonomy_receipt(db, command, payload_hash, "REJECTED", {"code": "CATEGORY_PARENT_INVALID"})
            ancestors = {category.id}
            cursor = parent
            while cursor is not None:
                if cursor.id in ancestors:
                    return await _taxonomy_receipt(db, command, payload_hash, "REJECTED", {"code": "CATEGORY_MOVE_CYCLE"})
                ancestors.add(cursor.id)
                cursor = await db.get(Category, cursor.parent_id) if cursor.parent_id else None
            category.parent_id = parent_uuid
            if move_data.position is not None:
                category.sort_order = move_data.position
        elif command.command_type == "CATEGORY_ARCHIVE":
            child = await db.scalar(select(Category.id).where(Category.parent_id == category.id).limit(1))
            if child is not None:
                return await _taxonomy_receipt(db, command, payload_hash, "REJECTED", {"code": "CATEGORY_HAS_CHILDREN"})
            product = await db.scalar(select(Product.id).where(Product.category_id == category.id, Product.deleted.is_(False)).limit(1))
            if product is not None:
                return await _taxonomy_receipt(db, command, payload_hash, "REJECTED", {"code": "CATEGORY_HAS_PRODUCTS"})
            category.status = "ARCHIVED"
            category.is_active = False
        elif command.command_type == "CATEGORY_PUBLISH":
            if category.status not in {"DRAFT", "REVIEW_PENDING"}:
                return await _taxonomy_receipt(db, command, payload_hash, "REJECTED", {"code": "CATEGORY_NOT_PUBLISHABLE"})
            category.status = "ACTIVE"
            category.is_active = True
        elif command.command_type == "ATTRIBUTE_RULES_PUBLISH":
            try:
                rules_data = CategoryRulesPayload.model_validate(
                    {key: value for key, value in data.items() if key != "impact_hash"}
                )
            except ValidationError:
                return await _taxonomy_receipt(db, command, payload_hash, "REJECTED", {"code": "INVALID_CATEGORY_RULES"})
            if rules_data.schema_version != category.schema_version + 1:
                return await _taxonomy_receipt(db, command, payload_hash, "REJECTED", {"code": "INVALID_CATEGORY_RULES"})
            if any(rule.condition is not None for rule in rules_data.rules):
                return await _taxonomy_receipt(db, command, payload_hash, "REJECTED", {"code": "CONDITIONAL_RULES_UNSUPPORTED"})
            attribute_ids = {rule.attribute_id for rule in rules_data.rules}
            if len(attribute_ids) != len(rules_data.rules):
                return await _taxonomy_receipt(db, command, payload_hash, "REJECTED", {"code": "DUPLICATE_ATTRIBUTE_RULE"})
            if attribute_ids:
                active_ids = set((await db.scalars(
                    select(AttributeDefinition.id).where(
                        AttributeDefinition.id.in_(attribute_ids),
                        AttributeDefinition.status == "ACTIVE",
                    )
                )).all())
                if active_ids != attribute_ids:
                    return await _taxonomy_receipt(db, command, payload_hash, "REJECTED", {"code": "ATTRIBUTE_NOT_FOUND"})
            category.schema_version = rules_data.schema_version
            category.attribute_rules = [rule.model_dump(mode="json") for rule in rules_data.rules]

    if command.command_type != "CATEGORY_CREATE":
        category.revision += 1

    if impact_preview is not None:
        impact_preview.consumed_by_command_id = command.command_id

    state.version += 1
    try:
        await db.flush()
        receipt = await _taxonomy_receipt(
            db, command, payload_hash, "APPLIED",
            {"aggregate_id": str(command.aggregate_id), "aggregate_version": category.revision, "taxonomy_version": state.version},
        )
    except IntegrityError:
        await db.rollback()
        existing = await _existing_taxonomy_receipt(db, command.command_id, payload_hash)
        if existing is not None:
            return existing
        # The command did not apply; persist a stable rejection for unique-code/slug failures.
        return await _taxonomy_receipt(db, command, payload_hash, "REJECTED", {"code": "CATEGORY_CODE_OR_SLUG_EXISTS"})
    return receipt


@router.get(
    "/taxonomy/commands/{command_id}",
    response_model=TaxonomyCommandReceiptResponse,
    operation_id="get__internal_v1_taxonomy_commands_command_id",
    openapi_extra={"x-allowed-service": "service:admin"},
)
async def get_taxonomy_command_receipt(
    command_id: UUID,
    _: None = Depends(verify_admin_service),
    db: AsyncSession = Depends(get_db),
) -> TaxonomyCommandReceiptResponse:
    receipt = await db.get(TaxonomyCommandReceipt, command_id)
    if receipt is None:
        raise HTTPException(status_code=404, detail={"code": "TAXONOMY_COMMAND_NOT_FOUND", "message": "Taxonomy command receipt not found"})
    return TaxonomyCommandReceiptResponse(command_id=receipt.command_id, status=receipt.status, result=receipt.result)


def _search_digest(search: str) -> str:
    return hashlib.sha256(search.casefold().encode("utf-8")).hexdigest()


def _encode_product_cursor(created_at: datetime, product_id: UUID, search: str) -> str:
    payload = [created_at.isoformat(), str(product_id), _search_digest(search)]
    return base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")


def _decode_product_cursor(
    value: str | None, search: str
) -> tuple[datetime, UUID] | None:
    if value is None:
        return None
    try:
        if len(value) > 1024:
            raise ValueError("cursor too long")
        raw = base64.b64decode(
            value + "=" * (-len(value) % 4), altchars=b"-_", validate=True
        )
        payload = json.loads(raw)
        if (
            not isinstance(payload, list)
            or len(payload) != 3
            or not all(isinstance(item, str) for item in payload)
            or payload[2] != _search_digest(search)
        ):
            raise ValueError("cursor does not match this search")
        created_at = datetime.fromisoformat(payload[0])
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError("cursor timestamp must include a timezone")
        return created_at, UUID(payload[1])
    except (
        binascii.Error,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
        TypeError,
        OverflowError,
        AttributeError,
    ) as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_CURSOR", "message": "Invalid product pagination cursor"},
        ) from exc


def _product_visibility(product: Product) -> tuple[bool, list[str]]:
    status = str(product.status)
    eligible_status = status == "MODERATED" or (
        status in {"ON_MODERATION", "BLOCKED"}
        and product.published_revision is not None
    )
    has_sellable_sku = any(
        sku.is_active
        and (sku.stock if sku.on_hand is None else sku.on_hand)
        - sku.reserved_quantity
        > 0
        for sku in product.skus
    )
    safety_hold_active = (
        (hold_until := getattr(product, "safety_hold_until", None)) is not None
        and hold_until > datetime.now(timezone.utc)
    )
    visible = bool(
        eligible_status
        and not product.deleted
        and product.category_id is not None
        and has_sellable_sku
        and not safety_hold_active
    )
    reasons: list[str] = []
    if not visible:
        if product.deleted:
            reasons.append("PRODUCT_DELETED")
        if product.category_id is None:
            reasons.append("CATEGORY_NOT_ASSIGNED")
        if status not in {"MODERATED", "ON_MODERATION", "BLOCKED"}:
            reasons.append("NOT_PUBLISHED")
        if status in {"ON_MODERATION", "BLOCKED"} and product.published_revision is None:
            reasons.append("NO_PUBLISHED_REVISION")
        if not has_sellable_sku and not reasons:
            reasons.append("NO_ACTIVE_SKU")
        if safety_hold_active:
            reasons.append("SAFETY_HOLD")
        if not reasons:
            reasons.append("NOT_IN_PUBLIC_CATALOG")
    return visible, reasons


@router.get(
    "/taxonomy/snapshot",
    response_model=AdminTaxonomySnapshotResponse,
    operation_id="get__internal_v1_taxonomy_snapshot",
    openapi_extra={"x-allowed-service": "service:admin"},
)
async def get_taxonomy_snapshot(
    _: None = Depends(verify_admin_service),
    db: AsyncSession = Depends(get_db),
) -> AdminTaxonomySnapshotResponse:
    state = await db.get(TaxonomyState, 1)
    if state is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "TAXONOMY_NOT_INITIALIZED", "message": "B2B taxonomy version state is not initialized"},
        )
    result = await db.execute(select(Category).order_by(Category.id))
    rows = list(result.scalars().all())
    by_id = {category.id: category for category in rows}

    def path_for(category: Category) -> str:
        segments: list[str] = []
        visited: set[UUID] = set()
        current: Category | None = category
        while current is not None:
            if current.id in visited:
                raise HTTPException(
                    status_code=503,
                    detail={"code": "TAXONOMY_CYCLE", "message": "B2B category hierarchy contains a cycle"},
                )
            visited.add(current.id)
            segments.append(current.slug)
            current = by_id.get(current.parent_id) if current.parent_id else None
        return "/" + "/".join(reversed(segments))

    categories = [
        AdminTaxonomyCategoryResponse(
            id=category.id,
            parent_id=category.parent_id,
            code=category.code,
            slug=category.slug,
            name=category.name,
            labels=category.labels or {},
            description=category.description,
            status=category.status,
            sort_order=category.sort_order,
            version=category.revision,
            path=path_for(category),
            seo_title=category.seo_title,
            image_media_id=category.image_media_id,
            schema_version=category.schema_version,
            attribute_rules=category.attribute_rules,
            updated_at=category.updated_at,
        )
        for category in rows
    ]
    attributes_result = await db.execute(
        select(AttributeDefinition)
        .where(AttributeDefinition.status == "ACTIVE")
        .order_by(AttributeDefinition.code, AttributeDefinition.id)
    )
    attributes = [
        AdminTaxonomyAttributeResponse(
            id=attribute.id,
            code=attribute.code,
            name=attribute.name,
            data_type=attribute.data_type,
            unit=attribute.unit,
            required=attribute.required,
            filterable=attribute.filterable,
            searchable=attribute.searchable,
            comparable=attribute.comparable,
            variant_dimension=attribute.variant_dimension,
            pii=attribute.pii,
            constraints=attribute.constraints,
            version=attribute.version,
        )
        for attribute in attributes_result.scalars().all()
    ]
    brand_rows = list((await db.scalars(select(Brand).order_by(Brand.normalized_name, Brand.id))).all())
    brand_ids = [brand.id for brand in brand_rows]
    alias_rows = list((await db.execute(
        select(BrandAlias.brand_id, BrandAlias.alias)
        .where(BrandAlias.brand_id.in_(brand_ids or {UUID(int=0)}))
        .order_by(BrandAlias.normalized_alias)
    )).all())
    aliases_by_brand: dict[UUID, list[str]] = {}
    for alias_brand_id, alias in alias_rows:
        aliases_by_brand.setdefault(alias_brand_id, []).append(alias)
    brands: list[AdminBrandResponse] = []
    for brand in brand_rows:
        brands.append(AdminBrandResponse(
            id=brand.id, name=brand.name, aliases=aliases_by_brand.get(brand.id, []), status=brand.status,
            evidence_ref=brand.evidence_ref, merged_into_id=brand.merged_into_id, version=brand.version,
        ))
    return AdminTaxonomySnapshotResponse(
        version=state.version,
        categories=categories,
        attributes=attributes,
        brands=brands,
        as_of=datetime.now(timezone.utc),
    )


@router.get(
    "/products",
    response_model=AdminProductPageResponse,
    operation_id="get__internal_v1_products",
    openapi_extra={"x-allowed-service": "service:admin"},
)
async def list_admin_products(
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    search: str | None = Query(default=None, max_length=200),
    _: None = Depends(verify_admin_service),
    db: AsyncSession = Depends(get_db),
) -> AdminProductPageResponse:
    normalized_search = " ".join((search or "").split())
    position = _decode_product_cursor(cursor, normalized_search)
    statement = select(Product).options(selectinload(Product.skus))
    if normalized_search:
        clauses = [
            Product.title.icontains(normalized_search, autoescape=True),
            Product.description.icontains(normalized_search, autoescape=True),
        ]
        try:
            product_id = UUID(normalized_search)
        except ValueError:
            product_id = None
        if product_id is not None:
            clauses.extend((Product.id == product_id, Product.seller_id == product_id))
        statement = statement.where(or_(*clauses))
    if position is not None:
        created_at, product_id = position
        statement = statement.where(
            or_(
                Product.created_at < created_at,
                and_(Product.created_at == created_at, Product.id < product_id),
            )
        )
    result = await db.execute(
        statement.order_by(Product.created_at.desc(), Product.id.desc()).limit(limit + 1)
    )
    rows = list(result.scalars().all())
    has_more = len(rows) > limit
    items = rows[:limit]
    return AdminProductPageResponse(
        items=[
            {
                "product_id": product.id,
                "seller_id": product.seller_id,
                "current_revision": product.revision,
                "published_revision": product.published_revision,
                "visible": (state := _product_visibility(product))[0],
                "visibility_reasons": state[1],
            }
            for product in items
        ],
        page={
            "has_more": has_more,
            "next_cursor": (
                _encode_product_cursor(items[-1].created_at, items[-1].id, normalized_search)
                if has_more and items
                else None
            ),
        },
    )
@router.get(
    "/products/{product_id}/publication",
    response_model=ProductPublicationResponse,
    operation_id="get__internal_v1_products_product_id_publication",
    openapi_extra={"x-allowed-service": "service:admin"},
)
async def get_product_publication(
    product_id: UUID,
    _: None = Depends(verify_admin_service),
    db: AsyncSession = Depends(get_db),
) -> ProductPublicationResponse:
    product = await ProductRepository(db).get_with_skus(product_id)
    if product is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "PRODUCT_NOT_FOUND", "message": "Product not found"},
        )

    visible, reasons = _product_visibility(product)

    return ProductPublicationResponse(
        product_id=product.id,
        current_revision=product.revision,
        published_revision=product.published_revision,
        visible=visible,
        visibility_reasons=reasons,
        updated_at=product.updated_at,
    )


@router.get(
    "/products/{product_id}/revisions/{revision}",
    response_model=ProductRevisionSnapshotResponse,
    operation_id="get__internal_v1_products_product_id_revisions_revision_",
    openapi_extra={"x-allowed-service": "service:admin"},
)
async def get_product_revision(
    product_id: UUID,
    revision: int,
    _: None = Depends(verify_admin_service),
    db: AsyncSession = Depends(get_db),
) -> ProductRevisionSnapshotResponse:
    if revision < 1:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_REVISION", "message": "Revision must be positive"},
        )

    result = await db.execute(
        select(ProductVersion).where(
            ProductVersion.product_id == product_id,
            ProductVersion.revision == revision,
        )
    )
    version = result.scalar_one_or_none()
    if version is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "PRODUCT_REVISION_NOT_FOUND",
                "message": "Immutable product revision not found",
            },
        )

    content = version.snapshot
    if not isinstance(content, dict):
        raise HTTPException(
            status_code=503,
            detail={
                "code": "PRODUCT_REVISION_INVALID",
                "message": "Stored product revision content is invalid",
            },
        )
    digest = hashlib.sha256(
        json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if digest != version.snapshot_hash:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "PRODUCT_REVISION_INTEGRITY_FAILED",
                "message": "Stored product revision failed its integrity check",
            },
        )

    media_refs: list[str] = []
    images = content.get("images", [])
    if isinstance(images, list):
        for ref in images:
            if isinstance(ref, str) and ref not in media_refs:
                media_refs.append(ref)
    skus = content.get("skus", [])
    if isinstance(skus, list):
        for sku in skus:
            if not isinstance(sku, dict) or not isinstance(sku.get("images"), list):
                continue
            for ref in sku["images"]:
                if isinstance(ref, str) and ref not in media_refs:
                    media_refs.append(ref)

    return ProductRevisionSnapshotResponse(
        product_id=version.product_id,
        seller_id=version.seller_id,
        revision=version.revision,
        snapshot_hash=version.snapshot_hash,
        content=content,
        media_refs=media_refs,
    )
