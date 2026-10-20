import base64
import hashlib
import hmac
import json
import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import require_permission
from src.api.router import AdminAPIRoute
from src.clients.b2b_client import B2BClient
from src.core.database import get_db
from src.models.admin_operation import AdminOperation
from src.models.audit_log import AuditLog
from src.schemas.admin import AdminOperationResponse, PublishInput
from src.schemas.taxonomy import (
    AttributeDefinitionView,
    AttributeInput,
    AttributePageResponse,
    AttributeValues,
    BrandPageResponse,
    CategoryInput,
    CategoryRuleInput,
    CategoryRulePageResponse,
    CategoryRuleSet,
    CategoryTreeResponse,
    CategoryView,
    ImpactPreviewJobResponse,
    ImpactPreviewResponse,
    BrandMergeInput,
    BrandInput,
    BrandVerificationInput,
    BrandMergePreviewInput,
    BrandMergePreviewResponse,
    BrandView,
    ImpactPreviewInput,
    CategoryMoveInput,
    CategoryArchiveInput,
    PageResponse,
    SchemaValidationError,
    SchemaValidationResponse,
)

router = APIRouter(route_class=AdminAPIRoute, tags=["taxonomy"])
_CATEGORY_FIELDS = set(CategoryView.model_fields)
_ATTRIBUTE_FIELDS = set(AttributeDefinitionView.model_fields)
_BRAND_FIELDS = set(BrandView.model_fields)


def _operation_response(operation: AdminOperation, request: Request) -> AdminOperationResponse:
    return AdminOperationResponse(
        operation_id=operation.id,
        status=operation.status,
        resource_id=operation.entity_id,
        request_id=getattr(request.state, "request_id", None),
        updated_at=operation.updated_at,
        version=operation.version,
    )


def _version(value: str) -> int:
    try:
        result = int(value.strip().strip('"').removeprefix("v"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "INVALID_IF_MATCH", "message": "If-Match must contain a positive version"}) from exc
    if result < 1:
        raise HTTPException(status_code=422, detail={"code": "INVALID_IF_MATCH", "message": "If-Match must contain a positive version"})
    return result


def _fingerprint(value: dict[str, object]) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


async def _existing_operation(
    *, actor: SimpleNamespace, idempotency_key: UUID, request_hash: str,
    request: Request, db: AsyncSession,
) -> AdminOperationResponse | None:
    prior = await db.scalar(select(AdminOperation).where(
        AdminOperation.requested_by == actor.id,
        AdminOperation.idempotency_key == str(idempotency_key),
    ))
    if prior is None:
        return None
    if not hmac.compare_digest(prior.request_hash, request_hash):
        raise HTTPException(status_code=409, detail={"code": "IDEMPOTENCY_KEY_REUSED", "message": "Idempotency key was used for a different operation"})
    return _operation_response(prior, request)


async def _propose_category_command(
    *,
    action: str,
    entity_id: UUID,
    expected_version: int,
    payload: dict[str, object],
    reason_code: str,
    actor: SimpleNamespace,
    request: Request,
    idempotency_key: UUID,
    request_hash: str,
    db: AsyncSession,
    entity_type: str = "category",
) -> AdminOperationResponse:
    prior = await db.scalar(select(AdminOperation).where(
        AdminOperation.requested_by == actor.id,
        AdminOperation.idempotency_key == str(idempotency_key),
    ))
    if prior is not None:
        if not hmac.compare_digest(prior.request_hash, request_hash):
            raise HTTPException(status_code=409, detail={"code": "IDEMPOTENCY_KEY_REUSED", "message": "Idempotency key was used for a different operation"})
        return _operation_response(prior, request)
    operation = AdminOperation(
        id=uuid4(),
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        payload={"expected_version": expected_version, "command_payload": payload},
        status="WAITING_APPROVAL",
        version=1,
        idempotency_key=str(idempotency_key),
        request_hash=request_hash,
        requested_by=actor.id,
        reason_code=reason_code,
        updated_at=datetime.now(timezone.utc),
    )
    db.add(operation)
    db.add(AuditLog(
        actor_id=actor.id,
        action=f"{action}_PROPOSED",
        entity_type=entity_type,
        entity_id=entity_id,
        details={"operation_id": str(operation.id), "expected_version": expected_version, "reason_code": reason_code},
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
        if prior is None or not hmac.compare_digest(prior.request_hash, request_hash):
            raise HTTPException(status_code=409, detail={"code": "IDEMPOTENCY_KEY_REUSED", "message": "Idempotency key conflicts with another operation"})
        operation = prior
    return _operation_response(operation, request)


async def _snapshot() -> dict[str, object]:
    try:
        snapshot = await B2BClient().get_internal_json("/internal/v1/taxonomy/snapshot")
    except HTTPException as exc:
        if exc.status_code == 404:
            raise HTTPException(status_code=503, detail={"code": "B2B_TAXONOMY_SNAPSHOT_UNAVAILABLE", "message": "B2B does not expose the Admin taxonomy snapshot contract"}) from exc
        raise
    version = snapshot.get("version")
    categories = snapshot.get("categories")
    attributes = snapshot.get("attributes", [])
    if not isinstance(version, int) or version < 1 or not isinstance(categories, list) or not isinstance(attributes, list):
        raise HTTPException(status_code=502, detail={"code": "B2B_INVALID_TAXONOMY_SNAPSHOT", "message": "B2B taxonomy snapshot does not match the Admin contract"})
    return snapshot


def _validated(model, value: object):
    try:
        return model.model_validate(value)
    except ValidationError as exc:
        raise HTTPException(status_code=502, detail={"code": "B2B_INVALID_TAXONOMY_SNAPSHOT", "message": "B2B taxonomy snapshot contains invalid data"}) from exc


def _category(raw: object) -> CategoryView:
    if not isinstance(raw, dict):
        raise HTTPException(status_code=502, detail={"code": "B2B_INVALID_TAXONOMY_SNAPSHOT", "message": "B2B returned an invalid category"})
    return _validated(CategoryView, {key: value for key, value in raw.items() if key in _CATEGORY_FIELDS})


def _attribute(raw: object) -> AttributeDefinitionView:
    if not isinstance(raw, dict):
        raise HTTPException(status_code=502, detail={"code": "B2B_INVALID_TAXONOMY_SNAPSHOT", "message": "B2B returned an invalid attribute"})
    return _validated(AttributeDefinitionView, {key: value for key, value in raw.items() if key in _ATTRIBUTE_FIELDS})


def _brand(raw: object) -> BrandView:
    if not isinstance(raw, dict):
        raise HTTPException(status_code=502, detail={"code": "B2B_INVALID_TAXONOMY_SNAPSHOT", "message": "B2B returned an invalid brand"})
    return _validated(BrandView, {key: value for key, value in raw.items() if key in _BRAND_FIELDS})


def _effective_category_rules(snapshot: dict[str, object], category_id: UUID) -> tuple[list[CategoryRuleInput], bool]:
    raw_categories = snapshot.get("categories")
    if not isinstance(raw_categories, list):
        raise HTTPException(status_code=502, detail={"code": "B2B_INVALID_TAXONOMY_SNAPSHOT", "message": "B2B returned invalid categories"})
    by_id = {
        UUID(str(row["id"])): row
        for row in raw_categories
        if isinstance(row, dict) and row.get("id")
    }
    chain: list[dict[str, object]] = []
    seen: set[UUID] = set()
    current_id: UUID | None = category_id
    while current_id is not None:
        if current_id in seen:
            raise HTTPException(status_code=502, detail={"code": "B2B_TAXONOMY_CYCLE", "message": "B2B taxonomy snapshot contains a parent cycle"})
        seen.add(current_id)
        current = by_id.get(current_id)
        if current is None:
            if not chain:
                raise HTTPException(status_code=404, detail={"code": "CATEGORY_NOT_FOUND", "message": "Category not found"})
            raise HTTPException(status_code=502, detail={"code": "B2B_TAXONOMY_PARENT_MISSING", "message": "B2B taxonomy snapshot has a missing parent"})
        chain.append(current)
        parent_id = current.get("parent_id")
        try:
            current_id = UUID(str(parent_id)) if parent_id is not None else None
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=502, detail={"code": "B2B_INVALID_TAXONOMY_SNAPSHOT", "message": "B2B returned an invalid parent ID"}) from exc
    rules_by_attribute: dict[UUID, CategoryRuleInput] = {}
    has_published_schema = False
    for category in reversed(chain):
        version = category.get("schema_version", 0)
        raw_rules = category.get("attribute_rules", [])
        if not isinstance(version, int) or version < 0 or not isinstance(raw_rules, list):
            raise HTTPException(status_code=502, detail={"code": "B2B_INVALID_TAXONOMY_SNAPSHOT", "message": "B2B returned invalid category rules"})
        if version == 0:
            continue
        has_published_schema = True
        try:
            parsed = [CategoryRuleInput.model_validate(rule) for rule in raw_rules]
        except ValidationError as exc:
            raise HTTPException(status_code=502, detail={"code": "B2B_INVALID_TAXONOMY_SNAPSHOT", "message": "B2B returned invalid category rules"}) from exc
        for rule in parsed:
            rules_by_attribute[rule.attribute_id] = rule
    return sorted(rules_by_attribute.values(), key=lambda rule: str(rule.attribute_id)), has_published_schema


@router.get("/admin/v1/taxonomy/categories", response_model=CategoryTreeResponse, response_model_exclude_none=True)
async def list_categories(
    _: SimpleNamespace = Depends(require_permission("taxonomy.category.read")),
) -> CategoryTreeResponse:
    snapshot = await _snapshot()
    items = [_category(row) for row in snapshot["categories"]]
    return CategoryTreeResponse(items=items, taxonomy_version=snapshot["version"])


@router.post("/admin/v1/taxonomy/categories", response_model=AdminOperationResponse, status_code=202, operation_id="POST_admin_v1_taxonomy_categories")
async def propose_category_create(
    data: CategoryInput,
    request: Request,
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    actor: SimpleNamespace = Depends(require_permission("taxonomy.category.write")),
    db: AsyncSession = Depends(get_db),
) -> AdminOperationResponse:
    command_payload = data.model_dump(mode="json", exclude_unset=True)
    request_hash = _fingerprint({"action": "CATEGORY_CREATE", "payload": command_payload})
    prior = await _existing_operation(actor=actor, idempotency_key=idempotency_key, request_hash=request_hash, request=request, db=db)
    if prior is not None:
        return prior
    snapshot = await _snapshot()
    categories = [_category(row) for row in snapshot["categories"]]
    if data.parent_id is not None and not any(item.id == data.parent_id and item.status in {"DRAFT", "ACTIVE"} for item in categories):
        raise HTTPException(status_code=422, detail={"code": "CATEGORY_PARENT_INVALID", "message": "Parent category is missing or archived"})
    if any(item.code.casefold() == data.code.casefold() or item.slug.casefold() == data.slug.casefold() for item in categories):
        raise HTTPException(status_code=409, detail={"code": "CATEGORY_CODE_OR_SLUG_EXISTS", "message": "Category code or slug already exists"})
    entity_id = uuid4()
    return await _propose_category_command(
        action="CATEGORY_CREATE",
        entity_id=entity_id,
        expected_version=int(snapshot["version"]),
        payload=command_payload,
        reason_code="TAXONOMY_CHANGE",
        actor=actor,
        request=request,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        db=db,
    )


@router.get("/admin/v1/taxonomy/categories/{category_id}", response_model=CategoryView, response_model_exclude_none=True)
async def get_category(
    category_id: UUID,
    _: SimpleNamespace = Depends(require_permission("taxonomy.category.read")),
) -> CategoryView:
    snapshot = await _snapshot()
    for raw in snapshot["categories"]:
        if isinstance(raw, dict) and str(raw.get("id")) == str(category_id):
            return _category(raw)
    raise HTTPException(status_code=404, detail={"code": "CATEGORY_NOT_FOUND", "message": "Category not found"})


@router.patch("/admin/v1/taxonomy/categories/{category_id}", response_model=AdminOperationResponse, status_code=202, operation_id="PATCH_admin_v1_taxonomy_categories_category_id")
async def propose_category_update(
    category_id: UUID,
    data: CategoryInput,
    request: Request,
    if_match: str = Header(alias="If-Match"),
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    actor: SimpleNamespace = Depends(require_permission("taxonomy.category.write")),
    db: AsyncSession = Depends(get_db),
) -> AdminOperationResponse:
    expected_version = _version(if_match)
    command_payload = data.model_dump(mode="json", exclude_unset=True)
    request_hash = _fingerprint({"action": "CATEGORY_UPDATE", "entity_id": str(category_id), "expected_version": expected_version, "payload": command_payload})
    prior = await _existing_operation(actor=actor, idempotency_key=idempotency_key, request_hash=request_hash, request=request, db=db)
    if prior is not None:
        return prior
    snapshot = await _snapshot()
    categories = [_category(row) for row in snapshot["categories"]]
    category = next((item for item in categories if item.id == category_id), None)
    if category is None:
        raise HTTPException(status_code=404, detail={"code": "CATEGORY_NOT_FOUND", "message": "Category not found"})
    if category.status == "ARCHIVED":
        raise HTTPException(status_code=409, detail={"code": "CATEGORY_ARCHIVED", "message": "Archived category cannot be edited"})
    if category.version != expected_version:
        raise HTTPException(status_code=412, detail={"code": "CATEGORY_VERSION_MISMATCH", "message": "Category changed; reload before editing"})
    if data.parent_id is not None and data.parent_id != category.parent_id:
        raise HTTPException(status_code=409, detail={"code": "CATEGORY_MOVE_REQUIRED", "message": "Parent changes must use the move workflow"})
    if data.parent_id is not None and not any(item.id == data.parent_id and item.status in {"DRAFT", "ACTIVE"} for item in categories):
        raise HTTPException(status_code=422, detail={"code": "CATEGORY_PARENT_INVALID", "message": "Parent category is missing or archived"})
    if any(item.id != category_id and (item.code.casefold() == data.code.casefold() or item.slug.casefold() == data.slug.casefold()) for item in categories):
        raise HTTPException(status_code=409, detail={"code": "CATEGORY_CODE_OR_SLUG_EXISTS", "message": "Category code or slug already exists"})
    return await _propose_category_command(
        action="CATEGORY_UPDATE",
        entity_id=category_id,
        expected_version=expected_version,
        payload=command_payload,
        reason_code="TAXONOMY_CHANGE",
        actor=actor,
        request=request,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        db=db,
    )


@router.post("/admin/v1/taxonomy/categories/{category_id}/impact-preview", response_model=ImpactPreviewResponse | ImpactPreviewJobResponse, responses={202: {"model": ImpactPreviewJobResponse}}, operation_id="POST_admin_v1_taxonomy_categories_category_id_impact_preview")
async def preview_category_impact(
    category_id: UUID,
    data: ImpactPreviewInput,
    http_response: Response,
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    _: SimpleNamespace = Depends(require_permission("taxonomy.category.read")),
) -> dict[str, object]:
    snapshot = await _snapshot()
    category_row = next((row for row in snapshot["categories"] if isinstance(row, dict) and str(row.get("id")) == str(category_id)), None)
    if category_row is None:
        raise HTTPException(status_code=404, detail={"code": "CATEGORY_NOT_FOUND", "message": "Category not found"})
    version = category_row.get("version")
    if not isinstance(version, int) or version < 1:
        raise HTTPException(status_code=502, detail={"code": "B2B_INVALID_TAXONOMY_SNAPSHOT", "message": "B2B returned an invalid category version"})
    body = data.model_dump(mode="json", exclude_none=True)
    b2b_response = await B2BClient().post_internal_json(
        f"/internal/v1/taxonomy/categories/{category_id}/impact-preview",
        body,
        idempotency_key=str(idempotency_key),
        if_match=f'"{version}"',
    )
    if "job_id" in b2b_response:
        try:
            job = ImpactPreviewJobResponse.model_validate(b2b_response)
        except ValidationError as exc:
            raise HTTPException(status_code=502, detail={"code": "B2B_INVALID_IMPACT_JOB", "message": "B2B returned an invalid taxonomy impact job"}) from exc
        if job.job_id != idempotency_key:
            raise HTTPException(status_code=502, detail={"code": "B2B_INVALID_IMPACT_JOB", "message": "B2B returned a job for a different request"})
        if job.status in {"QUEUED", "RUNNING"}:
            http_response.status_code = 202
        return job.model_dump(mode="json")
    try:
        preview = ImpactPreviewResponse.model_validate(b2b_response)
    except ValidationError as exc:
        raise HTTPException(status_code=502, detail={"code": "B2B_INVALID_IMPACT_PREVIEW", "message": "B2B returned an invalid taxonomy impact preview"}) from exc
    if preview.change_id != idempotency_key:
        raise HTTPException(status_code=502, detail={"code": "B2B_INVALID_IMPACT_PREVIEW", "message": "B2B returned a preview for a different request"})
    return preview.model_dump(mode="json")


@router.get("/admin/v1/taxonomy/impact-preview-jobs/{job_id}", response_model=ImpactPreviewJobResponse, operation_id="GET_admin_v1_taxonomy_impact_preview_jobs_job_id")
async def get_taxonomy_impact_job(
    job_id: UUID,
    _: SimpleNamespace = Depends(require_permission("taxonomy.category.read")),
) -> dict[str, object]:
    result = await B2BClient().get_internal_json(f"/internal/v1/taxonomy/impact-preview-jobs/{job_id}")
    try:
        job = ImpactPreviewJobResponse.model_validate(result)
    except ValidationError as exc:
        raise HTTPException(status_code=502, detail={"code": "B2B_INVALID_IMPACT_JOB", "message": "B2B returned an invalid taxonomy impact job"}) from exc
    if job.job_id != job_id:
        raise HTTPException(status_code=502, detail={"code": "B2B_INVALID_IMPACT_JOB", "message": "B2B returned a different taxonomy impact job"})
    return job.model_dump(mode="json")


@router.post("/admin/v1/taxonomy/categories/{category_id}/move", response_model=AdminOperationResponse, status_code=202, operation_id="POST_admin_v1_taxonomy_categories_category_id_move")
async def propose_category_move(
    category_id: UUID,
    data: CategoryMoveInput,
    request: Request,
    if_match: str = Header(alias="If-Match"),
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    actor: SimpleNamespace = Depends(require_permission("taxonomy.category.write")),
    db: AsyncSession = Depends(get_db),
) -> AdminOperationResponse:
    expected_version = _version(if_match)
    payload = data.model_dump(mode="json")
    request_hash = _fingerprint({"action": "CATEGORY_MOVE", "category_id": str(category_id), "expected_version": expected_version, "payload": payload})
    prior = await _existing_operation(actor=actor, idempotency_key=idempotency_key, request_hash=request_hash, request=request, db=db)
    if prior is not None:
        return prior
    categories = [_category(row) for row in (await _snapshot())["categories"]]
    category_by_id = {item.id: item for item in categories}
    category = category_by_id.get(category_id)
    parent = category_by_id.get(data.new_parent_id)
    if category is None:
        raise HTTPException(status_code=404, detail={"code": "CATEGORY_NOT_FOUND", "message": "Category not found"})
    if parent is None or parent.status not in {"DRAFT", "ACTIVE"}:
        raise HTTPException(status_code=422, detail={"code": "CATEGORY_PARENT_INVALID", "message": "New parent must exist and be active or draft"})
    if category.version != expected_version:
        raise HTTPException(status_code=412, detail={"code": "CATEGORY_VERSION_MISMATCH", "message": "Category changed; reload before moving"})
    if category_id == data.new_parent_id:
        raise HTTPException(status_code=409, detail={"code": "CATEGORY_MOVE_CYCLE", "message": "A category cannot be its own parent"})
    cursor = parent
    visited: set[UUID] = set()
    while cursor is not None:
        if cursor.id == category_id:
            raise HTTPException(status_code=409, detail={"code": "CATEGORY_MOVE_CYCLE", "message": "A category cannot be moved into its descendant"})
        if cursor.id in visited:
            raise HTTPException(status_code=502, detail={"code": "B2B_TAXONOMY_CYCLE", "message": "B2B taxonomy snapshot contains a parent cycle"})
        visited.add(cursor.id)
        cursor = category_by_id.get(cursor.parent_id) if cursor.parent_id else None
    return await _propose_category_command(
        action="CATEGORY_MOVE", entity_id=category_id, expected_version=expected_version,
        payload=payload, reason_code="TAXONOMY_CHANGE", actor=actor, request=request,
        idempotency_key=idempotency_key, request_hash=request_hash, db=db,
    )


@router.post("/admin/v1/taxonomy/categories/{category_id}/archive", response_model=AdminOperationResponse, status_code=202, operation_id="POST_admin_v1_taxonomy_categories_category_id_archive")
async def propose_category_archive(
    category_id: UUID,
    data: CategoryArchiveInput,
    request: Request,
    if_match: str = Header(alias="If-Match"),
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    actor: SimpleNamespace = Depends(require_permission("taxonomy.category.publish")),
    db: AsyncSession = Depends(get_db),
) -> AdminOperationResponse:
    expected_version = _version(if_match)
    payload = data.model_dump(mode="json")
    request_hash = _fingerprint({"action": "CATEGORY_ARCHIVE", "category_id": str(category_id), "expected_version": expected_version, "payload": payload})
    prior = await _existing_operation(actor=actor, idempotency_key=idempotency_key, request_hash=request_hash, request=request, db=db)
    if prior is not None:
        return prior
    categories = [_category(row) for row in (await _snapshot())["categories"]]
    category = next((item for item in categories if item.id == category_id), None)
    if category is None:
        raise HTTPException(status_code=404, detail={"code": "CATEGORY_NOT_FOUND", "message": "Category not found"})
    if category.version != expected_version:
        raise HTTPException(status_code=412, detail={"code": "CATEGORY_VERSION_MISMATCH", "message": "Category changed; reload before archiving"})
    if category.status == "ARCHIVED":
        raise HTTPException(status_code=409, detail={"code": "CATEGORY_ALREADY_ARCHIVED", "message": "Category is already archived"})
    return await _propose_category_command(
        action="CATEGORY_ARCHIVE", entity_id=category_id, expected_version=expected_version,
        payload=payload, reason_code=data.reason_code, actor=actor, request=request,
        idempotency_key=idempotency_key, request_hash=request_hash, db=db,
    )


@router.post("/admin/v1/taxonomy/categories/{category_id}/publish", response_model=AdminOperationResponse, status_code=202, operation_id="POST_admin_v1_taxonomy_categories_category_id_publish")
async def propose_category_publish(
    category_id: UUID,
    data: PublishInput,
    request: Request,
    if_match: str = Header(alias="If-Match"),
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    actor: SimpleNamespace = Depends(require_permission("taxonomy.category.publish")),
    db: AsyncSession = Depends(get_db),
) -> AdminOperationResponse:
    expected_version = _version(if_match)
    command_payload = data.model_dump(mode="json", exclude={"approved_by"})
    request_hash = _fingerprint({"action": "CATEGORY_PUBLISH", "entity_id": str(category_id), "expected_version": expected_version, "payload": command_payload})
    prior = await _existing_operation(actor=actor, idempotency_key=idempotency_key, request_hash=request_hash, request=request, db=db)
    if prior is not None:
        return prior
    snapshot = await _snapshot()
    categories = [_category(row) for row in snapshot["categories"]]
    category = next((item for item in categories if item.id == category_id), None)
    if category is None:
        raise HTTPException(status_code=404, detail={"code": "CATEGORY_NOT_FOUND", "message": "Category not found"})
    if category.version != expected_version:
        raise HTTPException(status_code=412, detail={"code": "CATEGORY_VERSION_MISMATCH", "message": "Category changed; reload before publishing"})
    if category.status not in {"DRAFT", "REVIEW_PENDING"}:
        raise HTTPException(status_code=409, detail={"code": "CATEGORY_NOT_PUBLISHABLE", "message": "Only draft or review-pending categories can be published"})
    return await _propose_category_command(
        action="CATEGORY_PUBLISH",
        entity_id=category_id,
        expected_version=expected_version,
        payload=command_payload,
        reason_code=data.reason_code,
        actor=actor,
        request=request,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        db=db,
    )


@router.put("/admin/v1/taxonomy/categories/{category_id}/attribute-rules", response_model=AdminOperationResponse, status_code=202, operation_id="PUT_admin_v1_taxonomy_categories_category_id_attribute_rules")
async def propose_category_rule_update(
    category_id: UUID,
    data: CategoryRuleSet,
    request: Request,
    if_match: str = Header(alias="If-Match"),
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    actor: SimpleNamespace = Depends(require_permission("taxonomy.attribute.write")),
    db: AsyncSession = Depends(get_db),
) -> AdminOperationResponse:
    expected_category_version = _version(if_match)
    payload = data.model_dump(mode="json")
    request_hash = _fingerprint({"action": "ATTRIBUTE_RULES_PUBLISH", "category_id": str(category_id), "expected_category_version": expected_category_version, "payload": payload})
    prior = await _existing_operation(actor=actor, idempotency_key=idempotency_key, request_hash=request_hash, request=request, db=db)
    if prior is not None:
        return prior
    snapshot = await _snapshot()
    raw_category = next((row for row in snapshot["categories"] if isinstance(row, dict) and str(row.get("id")) == str(category_id)), None)
    if raw_category is None:
        raise HTTPException(status_code=404, detail={"code": "CATEGORY_NOT_FOUND", "message": "Category not found"})
    category = _category(raw_category)
    if category.status == "ARCHIVED":
        raise HTTPException(status_code=409, detail={"code": "CATEGORY_ARCHIVED", "message": "Archived category rules cannot be changed"})
    if category.version != expected_category_version:
        raise HTTPException(status_code=412, detail={"code": "CATEGORY_VERSION_MISMATCH", "message": "Category changed; reload before editing its rules"})
    current_schema_version = raw_category.get("schema_version", 0)
    if not isinstance(current_schema_version, int) or current_schema_version < 0:
        raise HTTPException(status_code=502, detail={"code": "B2B_INVALID_TAXONOMY_SNAPSHOT", "message": "B2B returned an invalid category schema version"})
    if data.schema_version != current_schema_version + 1:
        raise HTTPException(status_code=409, detail={"code": "SCHEMA_VERSION_MISMATCH", "message": "Proposed schema_version must be the next version"})
    attribute_ids = {attribute.id for attribute in (_attribute(row) for row in snapshot["attributes"])}
    proposed_ids = [rule.attribute_id for rule in data.rules]
    if any(attribute_id not in attribute_ids for attribute_id in proposed_ids):
        raise HTTPException(status_code=422, detail={"code": "ATTRIBUTE_NOT_FOUND", "message": "A category rule references an unknown attribute"})
    if len(set(proposed_ids)) != len(proposed_ids):
        raise HTTPException(status_code=422, detail={"code": "DUPLICATE_ATTRIBUTE_RULE", "message": "Each attribute may appear only once in a category schema"})
    return await _propose_category_command(
        action="ATTRIBUTE_RULES_PUBLISH",
        entity_id=category_id,
        expected_version=expected_category_version,
        payload=payload,
        reason_code="ATTRIBUTE_SCHEMA_CHANGE",
        actor=actor,
        request=request,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        db=db,
    )


def _attribute_cursor(cursor: str | None) -> tuple[int, str, UUID] | None:
    if cursor is None:
        return None
    try:
        value = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")))
        version = int(value["v"])
        code = str(value["c"])
        attribute_id = UUID(value["id"])
        if version < 1 or not code:
            raise ValueError("invalid cursor data")
        return version, code, attribute_id
    except (ValueError, KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError, base64.binascii.Error) as exc:
        raise HTTPException(status_code=422, detail={"code": "INVALID_CURSOR", "message": "Invalid taxonomy cursor"}) from exc


def _encode_attribute_cursor(version: int, attribute: AttributeDefinitionView) -> str:
    raw = json.dumps({"v": version, "c": attribute.code, "id": str(attribute.id)}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode()


@router.get("/admin/v1/taxonomy/attributes", response_model=AttributePageResponse, response_model_exclude_none=True)
async def list_attributes(
    cursor: str | None = Query(None, max_length=1024),
    limit: int = Query(20, ge=1, le=100),
    _: SimpleNamespace = Depends(require_permission("taxonomy.attribute.read")),
) -> AttributePageResponse:
    snapshot = await _snapshot()
    position = _attribute_cursor(cursor)
    if position is not None and position[0] != snapshot["version"]:
        raise HTTPException(status_code=409, detail={"code": "TAXONOMY_SNAPSHOT_CHANGED", "message": "Taxonomy changed; restart pagination"})
    attributes = sorted((_attribute(row) for row in snapshot["attributes"]), key=lambda row: (row.code, str(row.id)))
    if position is not None:
        _, code, attribute_id = position
        attributes = [row for row in attributes if (row.code, str(row.id)) > (code, str(attribute_id))]
    page = attributes[:limit + 1]
    has_more = len(page) > limit
    items = page[:limit]
    return AttributePageResponse(
        items=items,
        page=PageResponse(has_more=has_more, next_cursor=_encode_attribute_cursor(snapshot["version"], items[-1]) if has_more and items else None),
    )


@router.post("/admin/v1/taxonomy/attributes", response_model=AdminOperationResponse, status_code=202, operation_id="POST_admin_v1_taxonomy_attributes")
async def propose_attribute_create(
    data: AttributeInput,
    request: Request,
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    actor: SimpleNamespace = Depends(require_permission("taxonomy.attribute.write")),
    db: AsyncSession = Depends(get_db),
) -> AdminOperationResponse:
    payload = data.model_dump(mode="json")
    request_hash = _fingerprint({"action": "ATTRIBUTE_CREATE", "payload": payload})
    prior = await _existing_operation(actor=actor, idempotency_key=idempotency_key, request_hash=request_hash, request=request, db=db)
    if prior is not None:
        return prior
    snapshot = await _snapshot()
    attributes = [_attribute(row) for row in snapshot["attributes"]]
    if any(row.code.casefold() == data.code.casefold() for row in attributes):
        raise HTTPException(status_code=409, detail={"code": "ATTRIBUTE_CODE_EXISTS", "message": "Attribute code already exists"})
    return await _propose_category_command(
        action="ATTRIBUTE_CREATE", entity_id=uuid4(), expected_version=snapshot["version"],
        payload={"draft_action": "CREATE", "attribute": payload}, reason_code="ATTRIBUTE_SCHEMA_CHANGE", actor=actor,
        request=request, idempotency_key=idempotency_key, request_hash=request_hash,
        db=db, entity_type="attribute",
    )


@router.patch("/admin/v1/taxonomy/attributes/{attribute_id}", response_model=AdminOperationResponse, status_code=202, operation_id="PATCH_admin_v1_taxonomy_attributes_attribute_id")
async def propose_attribute_update(
    attribute_id: UUID,
    data: AttributeInput,
    request: Request,
    if_match: str = Header(alias="If-Match"),
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    actor: SimpleNamespace = Depends(require_permission("taxonomy.attribute.write")),
    db: AsyncSession = Depends(get_db),
) -> AdminOperationResponse:
    expected_version = _version(if_match)
    payload = data.model_dump(mode="json")
    request_hash = _fingerprint({"action": "ATTRIBUTE_UPDATE", "attribute_id": str(attribute_id), "expected_version": expected_version, "payload": payload})
    prior = await _existing_operation(actor=actor, idempotency_key=idempotency_key, request_hash=request_hash, request=request, db=db)
    if prior is not None:
        return prior
    snapshot = await _snapshot()
    attributes = [_attribute(row) for row in snapshot["attributes"]]
    current = next((row for row in attributes if row.id == attribute_id), None)
    if current is None:
        raise HTTPException(status_code=404, detail={"code": "ATTRIBUTE_NOT_FOUND", "message": "Attribute not found"})
    if current.version != expected_version:
        raise HTTPException(status_code=412, detail={"code": "ATTRIBUTE_VERSION_MISMATCH", "message": "Attribute changed; reload before editing"})
    if any(row.id != attribute_id and row.code.casefold() == data.code.casefold() for row in attributes):
        raise HTTPException(status_code=409, detail={"code": "ATTRIBUTE_CODE_EXISTS", "message": "Attribute code already exists"})
    return await _propose_category_command(
        action="ATTRIBUTE_UPDATE", entity_id=attribute_id, expected_version=expected_version,
        payload={"draft_action": "UPDATE", "attribute": payload}, reason_code="ATTRIBUTE_SCHEMA_CHANGE", actor=actor,
        request=request, idempotency_key=idempotency_key, request_hash=request_hash,
        db=db, entity_type="attribute",
    )


def _brand_page_cursor(cursor: str | None) -> tuple[int, str, UUID] | None:
    if cursor is None:
        return None
    try:
        value = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")))
        version = int(value["v"])
        name = str(value["n"])
        brand_id = UUID(value["id"])
        if version < 1 or not name:
            raise ValueError("invalid cursor data")
        return version, name, brand_id
    except (ValueError, KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError, base64.binascii.Error) as exc:
        raise HTTPException(status_code=422, detail={"code": "INVALID_CURSOR", "message": "Invalid brand cursor"}) from exc


def _encode_brand_cursor(version: int, brand: BrandView) -> str:
    raw = json.dumps({"v": version, "n": brand.name.casefold(), "id": str(brand.id)}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode()


@router.get("/admin/v1/taxonomy/brands", response_model=BrandPageResponse, operation_id="GET_admin_v1_taxonomy_brands")
async def list_brands(
    cursor: str | None = Query(None, max_length=1024),
    limit: int = Query(20, ge=1, le=100),
    _: SimpleNamespace = Depends(require_permission("taxonomy.brand.read")),
) -> BrandPageResponse:
    snapshot = await _snapshot()
    raw_brands = snapshot.get("brands")
    if not isinstance(raw_brands, list):
        raise HTTPException(status_code=503, detail={"code": "B2B_BRAND_REGISTRY_UNAVAILABLE", "message": "B2B has not supplied the authoritative brand registry"})
    position = _brand_page_cursor(cursor)
    if position is not None and position[0] != snapshot["version"]:
        raise HTTPException(status_code=409, detail={"code": "TAXONOMY_SNAPSHOT_CHANGED", "message": "Brand registry changed; restart pagination"})
    brands = sorted((_brand(row) for row in raw_brands), key=lambda row: (row.name.casefold(), str(row.id)))
    if position is not None:
        _, name, brand_id = position
        brands = [row for row in brands if (row.name.casefold(), str(row.id)) > (name, str(brand_id))]
    page = brands[:limit + 1]
    has_more = len(page) > limit
    items = page[:limit]
    return BrandPageResponse(items=items, page=PageResponse(has_more=has_more, next_cursor=_encode_brand_cursor(snapshot["version"], items[-1]) if has_more and items else None))


@router.post("/admin/v1/taxonomy/brands", response_model=AdminOperationResponse, status_code=202, operation_id="POST_admin_v1_taxonomy_brands")
async def propose_brand_create(
    data: BrandInput,
    request: Request,
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    actor: SimpleNamespace = Depends(require_permission("taxonomy.brand.write")),
    db: AsyncSession = Depends(get_db),
) -> AdminOperationResponse:
    payload = data.model_dump(mode="json")
    request_hash = _fingerprint({"action": "BRAND_CREATE", "payload": payload})
    prior = await _existing_operation(actor=actor, idempotency_key=idempotency_key, request_hash=request_hash, request=request, db=db)
    if prior is not None:
        return prior
    snapshot = await _snapshot()
    brands = snapshot.get("brands")
    if not isinstance(brands, list):
        raise HTTPException(status_code=503, detail={"code": "B2B_BRAND_REGISTRY_UNAVAILABLE", "message": "B2B has not supplied the authoritative brand registry"})
    normalized = data.name.strip().casefold()
    if not normalized:
        raise HTTPException(status_code=422, detail={"code": "INVALID_BRAND", "message": "Brand name must not be blank"})
    if any(isinstance(row, dict) and str(row.get("name", "")).casefold() == normalized for row in brands):
        raise HTTPException(status_code=409, detail={"code": "BRAND_NAME_EXISTS", "message": "A brand with this name already exists"})
    return await _propose_category_command(
        action="BRAND_CREATE", entity_id=uuid4(), expected_version=int(snapshot["version"]),
        payload={"draft_action": "CREATE", "brand": payload}, reason_code="BRAND_CHANGE",
        actor=actor, request=request, idempotency_key=idempotency_key, request_hash=request_hash,
        db=db, entity_type="brand",
    )


@router.patch("/admin/v1/taxonomy/brands/{brand_id}", response_model=AdminOperationResponse, status_code=202, operation_id="PATCH_admin_v1_taxonomy_brands_brand_id")
async def propose_brand_update(
    brand_id: UUID,
    data: BrandInput,
    request: Request,
    if_match: str = Header(alias="If-Match"),
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    actor: SimpleNamespace = Depends(require_permission("taxonomy.brand.write")),
    db: AsyncSession = Depends(get_db),
) -> AdminOperationResponse:
    expected_version = _version(if_match)
    payload = data.model_dump(mode="json")
    request_hash = _fingerprint({"action": "BRAND_UPDATE", "brand_id": str(brand_id), "expected_version": expected_version, "payload": payload})
    prior = await _existing_operation(actor=actor, idempotency_key=idempotency_key, request_hash=request_hash, request=request, db=db)
    if prior is not None:
        return prior
    snapshot = await _snapshot()
    brands = snapshot.get("brands")
    if not isinstance(brands, list):
        raise HTTPException(status_code=503, detail={"code": "B2B_BRAND_REGISTRY_UNAVAILABLE", "message": "B2B has not supplied the authoritative brand registry"})
    parsed = [_brand(row) for row in brands]
    current = next((row for row in parsed if row.id == brand_id), None)
    if current is None:
        raise HTTPException(status_code=404, detail={"code": "BRAND_NOT_FOUND", "message": "Brand not found"})
    if current.version != expected_version:
        raise HTTPException(status_code=412, detail={"code": "BRAND_VERSION_MISMATCH", "message": "Brand changed; reload before editing"})
    if current.status in {"RESTRICTED", "MERGED"}:
        raise HTTPException(status_code=409, detail={"code": "BRAND_NOT_EDITABLE", "message": "Restricted or merged brands cannot be edited"})
    if any(row.id != brand_id and row.name.casefold() == data.name.strip().casefold() for row in parsed):
        raise HTTPException(status_code=409, detail={"code": "BRAND_NAME_EXISTS", "message": "A brand with this name already exists"})
    return await _propose_category_command(
        action="BRAND_UPDATE", entity_id=brand_id, expected_version=expected_version,
        payload={"draft_action": "UPDATE", "brand": payload}, reason_code="BRAND_CHANGE",
        actor=actor, request=request, idempotency_key=idempotency_key, request_hash=request_hash,
        db=db, entity_type="brand",
    )


@router.post("/admin/v1/taxonomy/brands/{brand_id}/verify", response_model=AdminOperationResponse, status_code=202, operation_id="POST_admin_v1_taxonomy_brands_brand_id_verify")
async def propose_brand_verification(
    brand_id: UUID,
    data: BrandVerificationInput,
    request: Request,
    if_match: str = Header(alias="If-Match"),
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    actor: SimpleNamespace = Depends(require_permission("taxonomy.brand.publish")),
    db: AsyncSession = Depends(get_db),
) -> AdminOperationResponse:
    expected_version = _version(if_match)
    snapshot = await _snapshot()
    brands = snapshot.get("brands")
    if not isinstance(brands, list):
        raise HTTPException(status_code=503, detail={"code": "B2B_BRAND_REGISTRY_UNAVAILABLE", "message": "B2B has not supplied the authoritative brand registry"})
    current = next((row for row in (_brand(item) for item in brands) if row.id == brand_id), None)
    if current is None:
        raise HTTPException(status_code=404, detail={"code": "BRAND_NOT_FOUND", "message": "Brand not found"})
    if current.version != expected_version:
        raise HTTPException(status_code=412, detail={"code": "BRAND_VERSION_MISMATCH", "message": "Brand changed; reload before verification"})
    if current.status != "DRAFT" or current.evidence_ref != data.evidence_ref:
        raise HTTPException(status_code=409, detail={"code": "BRAND_EVIDENCE_MISMATCH", "message": "Verification evidence must match the draft evidence reference"})
    payload = {"evidence_ref": data.evidence_ref}
    request_hash = _fingerprint({"action": "BRAND_VERIFY", "brand_id": str(brand_id), "expected_version": expected_version, "payload": payload, "reason_code": data.reason_code})
    prior = await _existing_operation(actor=actor, idempotency_key=idempotency_key, request_hash=request_hash, request=request, db=db)
    if prior is not None:
        return prior
    return await _propose_category_command(
        action="BRAND_VERIFY", entity_id=brand_id, expected_version=expected_version,
        payload=payload, reason_code=data.reason_code, actor=actor, request=request,
        idempotency_key=idempotency_key, request_hash=request_hash, db=db, entity_type="brand",
    )


@router.post("/admin/v1/taxonomy/brands/{brand_id}/merge-preview", response_model=BrandMergePreviewResponse, operation_id="POST_admin_v1_taxonomy_brands_brand_id_merge_preview")
async def preview_brand_merge(
    brand_id: UUID,
    data: BrandMergePreviewInput,
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    _: SimpleNamespace = Depends(require_permission("taxonomy.brand.read")),
) -> BrandMergePreviewResponse:
    snapshot = await _snapshot()
    brands = snapshot.get("brands")
    if not isinstance(brands, list):
        raise HTTPException(status_code=503, detail={"code": "B2B_BRAND_REGISTRY_UNAVAILABLE", "message": "B2B has not supplied the authoritative brand registry"})
    parsed = [_brand(row) for row in brands]
    source = next((row for row in parsed if row.id == brand_id), None)
    if source is None:
        raise HTTPException(status_code=404, detail={"code": "BRAND_NOT_FOUND", "message": "Brand not found"})
    response = await B2BClient().post_internal_json(
        f"/internal/v1/taxonomy/brands/{brand_id}/merge-preview",
        {"target_brand_id": str(data.target_brand_id)},
        idempotency_key=str(idempotency_key), if_match=f'"{source.version}"',
    )
    try:
        preview = BrandMergePreviewResponse.model_validate(response)
    except ValidationError as exc:
        raise HTTPException(status_code=502, detail={"code": "B2B_INVALID_BRAND_PREVIEW", "message": "B2B returned an invalid brand merge preview"}) from exc
    if preview.change_id != idempotency_key or preview.source_brand_id != brand_id or preview.target_brand_id != data.target_brand_id:
        raise HTTPException(status_code=502, detail={"code": "B2B_INVALID_BRAND_PREVIEW", "message": "B2B returned a preview for different brand IDs"})
    return preview


@router.post("/admin/v1/taxonomy/brands/{brand_id}/merge", response_model=AdminOperationResponse, status_code=202, operation_id="POST_admin_v1_taxonomy_brands_brand_id_merge")
async def propose_brand_merge(
    brand_id: UUID,
    data: BrandMergeInput,
    request: Request,
    if_match: str = Header(alias="If-Match"),
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    actor: SimpleNamespace = Depends(require_permission("taxonomy.brand.publish")),
    db: AsyncSession = Depends(get_db),
) -> AdminOperationResponse:
    expected_version = _version(if_match)
    if brand_id == data.target_brand_id:
        raise HTTPException(status_code=422, detail={"code": "BRAND_MERGE_SELF", "message": "A brand cannot be merged into itself"})
    payload = data.model_dump(mode="json")
    request_hash = _fingerprint({"action": "BRAND_MERGE", "brand_id": str(brand_id), "expected_version": expected_version, "payload": payload})
    prior = await _existing_operation(actor=actor, idempotency_key=idempotency_key, request_hash=request_hash, request=request, db=db)
    if prior is not None:
        return prior
    return await _propose_category_command(
        action="BRAND_MERGE", entity_id=brand_id, expected_version=expected_version,
        payload=payload, reason_code=data.reason_code, actor=actor, request=request,
        idempotency_key=idempotency_key, request_hash=request_hash, db=db,
        entity_type="brand",
    )


@router.get("/admin/v1/taxonomy/categories/{category_id}/attribute-rules", response_model=CategoryRulePageResponse, response_model_exclude_none=True)
async def get_category_rules(
    category_id: UUID,
    _: SimpleNamespace = Depends(require_permission("taxonomy.attribute.read")),
) -> CategoryRulePageResponse:
    snapshot = await _snapshot()
    category = next((raw for raw in snapshot["categories"] if isinstance(raw, dict) and str(raw.get("id")) == str(category_id)), None)
    if category is None:
        raise HTTPException(status_code=404, detail={"code": "CATEGORY_NOT_FOUND", "message": "Category not found"})
    rules = category.get("attribute_rules")
    schema_version = category.get("schema_version")
    if not isinstance(rules, list) or not isinstance(schema_version, int) or schema_version < 0:
        raise HTTPException(status_code=503, detail={"code": "CATEGORY_RULES_UNAVAILABLE", "message": "B2B has not supplied typed category attribute rules"})
    try:
        parsed = [CategoryRuleInput.model_validate(row) for row in rules]
    except ValidationError as exc:
        raise HTTPException(status_code=502, detail={"code": "B2B_INVALID_TAXONOMY_SNAPSHOT", "message": "B2B returned invalid category attribute rules"}) from exc
    return CategoryRulePageResponse(items=parsed, schema_version=schema_version)


def _value_error(data_type: str, value: object, constraints: dict[str, object]) -> tuple[str, str] | None:
    numeric: Decimal | None = None
    if data_type == "string":
        if not isinstance(value, str):
            return "TYPE_MISMATCH", "Expected a string"
        try:
            minimum_length = int(constraints.get("min_length", 0))
            maximum_length = int(constraints["max_length"]) if "max_length" in constraints else None
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=502, detail={"code": "B2B_INVALID_ATTRIBUTE_CONSTRAINT", "message": "B2B supplied an invalid string-length constraint"}) from exc
        if minimum_length < 0 or (maximum_length is not None and maximum_length < minimum_length):
            raise HTTPException(status_code=502, detail={"code": "B2B_INVALID_ATTRIBUTE_CONSTRAINT", "message": "B2B supplied an invalid string-length constraint"})
        if len(value) < minimum_length:
            return "MIN_LENGTH", "Value is shorter than the minimum length"
        if maximum_length is not None and len(value) > maximum_length:
            return "MAX_LENGTH", "Value exceeds the maximum length"
        pattern = constraints.get("pattern")
        if pattern is not None:
            if not isinstance(pattern, str) or len(pattern) > 128:
                raise HTTPException(status_code=502, detail={"code": "B2B_INVALID_ATTRIBUTE_CONSTRAINT", "message": "B2B supplied an invalid attribute pattern"})
            if len(value) > 4096:
                return "PATTERN_VALIDATION_LIMIT", "Value exceeds the pattern-validation size limit"
            if _high_cost_pattern(pattern):
                raise HTTPException(status_code=503, detail={"code": "ATTRIBUTE_PATTERN_UNSUPPORTED", "message": "B2B attribute pattern uses an unsupported high-cost expression"})
            try:
                if re.fullmatch(pattern, value) is None:
                    return "PATTERN_MISMATCH", "Value does not match the required format"
            except re.error as exc:
                raise HTTPException(status_code=502, detail={"code": "B2B_INVALID_ATTRIBUTE_CONSTRAINT", "message": "B2B supplied an invalid attribute pattern"}) from exc
    elif data_type == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            return "TYPE_MISMATCH", "Expected an integer"
        numeric = Decimal(value)
    elif data_type == "decimal":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return "TYPE_MISMATCH", "Expected a finite number"
        try:
            numeric = Decimal(str(value))
        except InvalidOperation:
            return "TYPE_MISMATCH", "Expected a finite number"
        if not numeric.is_finite():
            return "TYPE_MISMATCH", "Expected a finite number"
    elif data_type == "boolean":
        if not isinstance(value, bool):
            return "TYPE_MISMATCH", "Expected a boolean"
    elif data_type == "enum":
        if not isinstance(value, str):
            return "TYPE_MISMATCH", "Expected one string option"
    elif data_type == "multi_enum":
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            return "TYPE_MISMATCH", "Expected a list of string options"
        try:
            minimum_items = int(constraints.get("min_items", 0))
            maximum_items = int(constraints["max_items"]) if "max_items" in constraints else None
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=502, detail={"code": "B2B_INVALID_ATTRIBUTE_CONSTRAINT", "message": "B2B supplied an invalid item-count constraint"}) from exc
        if minimum_items < 0 or (maximum_items is not None and maximum_items < minimum_items):
            raise HTTPException(status_code=502, detail={"code": "B2B_INVALID_ATTRIBUTE_CONSTRAINT", "message": "B2B supplied an invalid item-count constraint"})
        if len(value) < minimum_items:
            return "MIN_ITEMS", "Select more values"
        if maximum_items is not None and len(value) > maximum_items:
            return "MAX_ITEMS", "Selected values exceed the maximum count"
        if constraints.get("unique_items") is True and len(set(value)) != len(value):
            return "DUPLICATE_ITEMS", "Selected values must be unique"
    elif data_type == "date":
        if not isinstance(value, str):
            return "TYPE_MISMATCH", "Expected an ISO date string"
        try:
            date.fromisoformat(value)
        except ValueError:
            return "INVALID_DATE", "Expected an ISO date string"
        for bound_key, comparator, code, message in (
            ("minimum", lambda v, b: v < b, "MINIMUM", "Date is before the minimum"),
            ("maximum", lambda v, b: v > b, "MAXIMUM", "Date is after the maximum"),
        ):
            bound = constraints.get(bound_key)
            if bound is not None:
                try:
                    parsed_bound = date.fromisoformat(str(bound))
                except ValueError as exc:
                    raise HTTPException(status_code=502, detail={"code": "B2B_INVALID_ATTRIBUTE_CONSTRAINT", "message": "B2B supplied an invalid date constraint"}) from exc
                if comparator(date.fromisoformat(value), parsed_bound):
                    return code, message
    elif data_type == "reference":
        if not isinstance(value, str):
            return "TYPE_MISMATCH", "Expected a reference ID string"
        try:
            UUID(value)
        except ValueError:
            return "INVALID_REFERENCE", "Expected a UUID reference"
    else:
        raise HTTPException(status_code=502, detail={"code": "B2B_INVALID_ATTRIBUTE_TYPE", "message": "B2B supplied an unsupported attribute type"})

    allowed = constraints.get("allowed", constraints.get("allowed_values", constraints.get("values")))
    if allowed is not None:
        if not isinstance(allowed, list):
            raise HTTPException(status_code=502, detail={"code": "B2B_INVALID_ATTRIBUTE_CONSTRAINT", "message": "B2B supplied an invalid allowed-values constraint"})
        candidates = value if data_type == "multi_enum" else [value]
        if any(candidate not in allowed for candidate in candidates):
            return "VALUE_NOT_ALLOWED", "Value is not in the allowed set"
    if numeric is not None:
        minimum = constraints.get("minimum", constraints.get("min"))
        maximum = constraints.get("maximum", constraints.get("max"))
        try:
            minimum_number = Decimal(str(minimum)) if minimum is not None else None
            maximum_number = Decimal(str(maximum)) if maximum is not None else None
            if (minimum_number is not None and not minimum_number.is_finite()) or (maximum_number is not None and not maximum_number.is_finite()) or (minimum_number is not None and maximum_number is not None and minimum_number > maximum_number):
                raise HTTPException(status_code=502, detail={"code": "B2B_INVALID_ATTRIBUTE_CONSTRAINT", "message": "B2B supplied invalid numeric bounds"})
            if minimum_number is not None and numeric < minimum_number:
                return "MINIMUM", "Value is below the minimum"
            if maximum_number is not None and numeric > maximum_number:
                return "MAXIMUM", "Value exceeds the maximum"
        except InvalidOperation as exc:
            raise HTTPException(status_code=502, detail={"code": "B2B_INVALID_ATTRIBUTE_CONSTRAINT", "message": "B2B supplied an invalid numeric constraint"}) from exc
    return None


def _high_cost_pattern(pattern: str) -> bool:
    # shortcut: reject multi-quantifier and advanced regex; replace with a timed evaluator when approved.
    groups: list[bool] = []
    quantifiers = 0
    in_character_class = False
    last_group_hazard = False
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "\\":
            index += 1
            if index < len(pattern) and pattern[index].isdigit():
                return True
            last_group_hazard = False
        elif in_character_class:
            if char == "]":
                in_character_class = False
        elif char == "[":
            in_character_class = True
            last_group_hazard = False
        elif char == "(":
            if pattern.startswith("(?", index) and not pattern.startswith("(?:", index):
                return True
            if pattern.startswith("(?:", index):
                index += 2
            groups.append(False)
            last_group_hazard = False
        elif char == ")":
            if not groups:
                return False
            last_group_hazard = groups.pop()
            if groups and last_group_hazard:
                groups[-1] = True
        elif char == "|":
            if groups:
                groups[-1] = True
            last_group_hazard = False
        elif char in "*+?":
            quantifiers += 1
            if quantifiers > 1 or last_group_hazard:
                return True
            if groups:
                groups[-1] = True
            last_group_hazard = False
        elif char == "{" and re.match(r"\{\d+(?:,\d*)?\}", pattern[index:]):
            quantifiers += 1
            if quantifiers > 1 or last_group_hazard:
                return True
            if groups:
                groups[-1] = True
            last_group_hazard = False
        else:
            last_group_hazard = False
        index += 1
    return False


@router.post("/admin/v1/taxonomy/categories/{category_id}/schema-validate", response_model=SchemaValidationResponse, operation_id="POST_admin_v1_taxonomy_categories_category_id_schema_validate")
async def validate_category_schema(
    category_id: UUID,
    data: AttributeValues,
    _: SimpleNamespace = Depends(require_permission("taxonomy.attribute.read")),
) -> SchemaValidationResponse:
    snapshot = await _snapshot()
    chain_rules, schema_is_published = _effective_category_rules(snapshot, category_id)
    if not schema_is_published:
        raise HTTPException(status_code=503, detail={"code": "CATEGORY_RULES_UNAVAILABLE", "message": "B2B has not supplied typed category attribute rules"})
    rules = chain_rules
    attributes = [_attribute(row) for row in snapshot["attributes"]]
    by_id = {str(attribute.id): attribute for attribute in attributes}
    if len(by_id) != len(attributes) or len({attribute.code for attribute in attributes}) != len(attributes):
        raise HTTPException(status_code=502, detail={"code": "B2B_INVALID_TAXONOMY_SNAPSHOT", "message": "B2B returned duplicate attribute IDs or codes"})
    if any(rule.attribute_id not in {attribute.id for attribute in attributes} for rule in rules):
        raise HTTPException(status_code=502, detail={"code": "B2B_INCOMPLETE_TAXONOMY_SNAPSHOT", "message": "A category rule references a missing attribute definition"})
    if any(rule.condition is not None for rule in rules):
        raise HTTPException(status_code=503, detail={"code": "CONDITIONAL_RULES_UNSUPPORTED", "message": "B2B conditional rules require an authoritative validation evaluator"})
    errors: list[SchemaValidationError] = []
    known_codes = {attribute.code for attribute in attributes if attribute.id in {rule.attribute_id for rule in rules}}
    for code in sorted(set(data.values) - known_codes):
        escaped = code.replace("~", "~0").replace("/", "~1")
        errors.append(SchemaValidationError(field_path=f"/values/{escaped}", code="UNKNOWN_ATTRIBUTE", message="Attribute is not defined for this category"))
    for rule in rules:
        attribute = by_id[str(rule.attribute_id)]
        if attribute.code not in data.values or data.values[attribute.code] is None:
            if rule.required or attribute.required:
                errors.append(SchemaValidationError(field_path=f"/values/{attribute.code}", code="REQUIRED", message="A value is required"))
            continue
        constraints = attribute.constraints or {}
        issue = _value_error(attribute.data_type, data.values[attribute.code], constraints)
        if issue:
            code, message = issue
            errors.append(SchemaValidationError(field_path=f"/values/{attribute.code}", code=code, message=message))
    return SchemaValidationResponse(valid=not errors, errors=errors)
