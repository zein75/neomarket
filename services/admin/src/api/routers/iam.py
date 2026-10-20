import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from pydantic import ValidationError
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import ROLE_PERMISSIONS, SELLER_SCOPED_PERMISSIONS, require_permission, require_recent_step_up, get_current_moderator
from src.api.router import AdminAPIRoute
from src.api.pagination import datetime_cursor, decode_cursor, encode_cursor
from src.core.config import settings
from src.core.database import get_db
from src.models.admin_operation import AdminOperation
from src.models.audit_log import AuditLog
from src.models.staff_principal import StaffPrincipal, StaffRoleGrant
from src.models.moderation import BlockingReason
from src.models.moderation_outbox_event import ModerationOutboxEvent
from src.models.admin_policy import AdminPolicy
from src.services.runtime_settings import validate_policy_rules
from src.models.complaint import Complaint, ComplaintAction as ComplaintActionRow
from src.schemas.admin import AdminOperationResponse, OperationReviewResponse, PermissionChange, PermissionGrantRevocation, ReasonAction
from src.schemas.admin_responses import OperationReviewPageResponse, PrincipalResponse, StaffPageResponse, StaffProfileResponse
from src.schemas.products import HoldInput
from src.schemas.sellers import SellerRestrictionInput

router = APIRouter(route_class=AdminAPIRoute, tags=["identity", "staff", "operations"])
PERMISSION_CODES = frozenset(
    permission
    for permissions in ROLE_PERMISSIONS.values()
    for permission in permissions
    if permission != "*"
)
TAXONOMY_ACTIONS = frozenset({
    "CATEGORY_CREATE", "CATEGORY_UPDATE", "CATEGORY_PUBLISH", "CATEGORY_MOVE", "CATEGORY_ARCHIVE",
    "ATTRIBUTE_RULES_PUBLISH", "ATTRIBUTE_CREATE", "ATTRIBUTE_UPDATE",
    "BRAND_CREATE", "BRAND_UPDATE", "BRAND_VERIFY", "BRAND_MERGE",
})
ACTION_APPROVAL_PERMISSIONS: dict[str, frozenset[str]] = {
    "STAFF_PERMISSION_GRANT": frozenset({"iam.grant"}),
    "STAFF_PERMISSION_REVOKE": frozenset({"iam.revoke"}),
    "STAFF_SESSION_REVOKE": frozenset({"iam.revoke"}),
    "BLOCKING_REASON_CREATE": frozenset({"policy.reason.write"}),
    "BLOCKING_REASON_UPDATE": frozenset({"policy.reason.write"}),
    "BLOCKING_REASON_ARCHIVE": frozenset({"policy.reason.write"}),
    "POLICY_CREATE": frozenset({"policy.write"}),
    "POLICY_PUBLISH": frozenset({"policy.publish"}),
    "OUTBOX_RETRY": frozenset({"operations.events.retry"}),
    "APPEAL_DECISION": frozenset({"appeal.decide"}),
    "COMPLAINT_ACTION": frozenset({"complaint.decide"}),
    "SELLER_RESTRICTION": frozenset({"seller.restrict"}),
    "PRODUCT_SAFETY_HOLD": frozenset({"products.safety_hold"}),
}


def _approval_permission(action: str) -> frozenset[str]:
    if action in TAXONOMY_ACTIONS:
        if action in {"ATTRIBUTE_RULES_PUBLISH", "ATTRIBUTE_CREATE", "ATTRIBUTE_UPDATE"}:
            return frozenset({"taxonomy.attribute.publish"})
        if action in {"BRAND_CREATE", "BRAND_UPDATE", "BRAND_VERIFY", "BRAND_MERGE"}:
            return frozenset({"taxonomy.brand.publish"})
        return frozenset({"taxonomy.category.publish"})
    return ACTION_APPROVAL_PERMISSIONS.get(action, frozenset({"operations.approve"}))


def _seller_scope_visible(operation: AdminOperation, actor: SimpleNamespace) -> bool:
    if operation.action != "SELLER_RESTRICTION" or "*" in actor.permissions:
        return True
    scopes = getattr(actor, "permission_scopes", {}).get("seller.restrict", set())
    return "*" in scopes or f"seller:{operation.entity_id}" in scopes


def _operation_visible(operation: AdminOperation, actor: SimpleNamespace) -> bool:
    if operation.requested_by == actor.id:
        return True
    if not _seller_scope_visible(operation, actor):
        return False
    if actor.id in {operation.approved_by, operation.cancelled_by}:
        return True
    if operation.status != "WAITING_APPROVAL":
        return False
    return (
        "*" in actor.permissions
        or bool(_approval_permission(operation.action) & actor.permissions)
    )


def _reviewable_operation_filter(actor: SimpleNamespace):
    if "*" in actor.permissions:
        return AdminOperation.status == "WAITING_APPROVAL"
    actions = {
        action
        for action, permissions in ACTION_APPROVAL_PERMISSIONS.items()
        if permissions & actor.permissions
    }
    for action in TAXONOMY_ACTIONS:
        if _approval_permission(action) & actor.permissions:
            actions.add(action)
    if "seller.restrict" in actor.permissions:
        scopes = getattr(actor, "permission_scopes", {}).get("seller.restrict", set())
        if scopes:
            actions.add("SELLER_RESTRICTION")
    clauses = []
    unrestricted_actions = actions - {"SELLER_RESTRICTION"}
    if unrestricted_actions:
        clauses.append(AdminOperation.action.in_(unrestricted_actions))
    if "operations.approve" in actor.permissions:
        known_actions = set(ACTION_APPROVAL_PERMISSIONS) | set(TAXONOMY_ACTIONS)
        clauses.append(AdminOperation.action.not_in(known_actions))
    seller_scopes = getattr(actor, "permission_scopes", {}).get("seller.restrict", set())
    if "SELLER_RESTRICTION" in actions:
        if "*" in seller_scopes:
            clauses.append(AdminOperation.action == "SELLER_RESTRICTION")
        else:
            seller_ids = []
            for scope in seller_scopes:
                if scope.startswith("seller:"):
                    try:
                        seller_ids.append(UUID(scope.removeprefix("seller:")))
                    except ValueError:
                        continue
        if "*" not in seller_scopes and seller_ids:
            clauses.append(and_(
                AdminOperation.action == "SELLER_RESTRICTION",
                AdminOperation.entity_id.in_(seller_ids),
            ))
    if not clauses:
        return None
    return and_(AdminOperation.status == "WAITING_APPROVAL", or_(*clauses))


def _reviewed_operation_filter(actor: SimpleNamespace):
    reviewer = or_(
        AdminOperation.approved_by == actor.id,
        AdminOperation.cancelled_by == actor.id,
    )
    clauses = [and_(AdminOperation.action != "SELLER_RESTRICTION", reviewer)]
    if "*" in actor.permissions:
        clauses.append(and_(AdminOperation.action == "SELLER_RESTRICTION", reviewer))
    else:
        scopes = getattr(actor, "permission_scopes", {}).get("seller.restrict", set())
        if "*" in scopes:
            clauses.append(and_(AdminOperation.action == "SELLER_RESTRICTION", reviewer))
        else:
            seller_ids = []
            for scope in scopes:
                if scope.startswith("seller:"):
                    try:
                        seller_ids.append(UUID(scope.removeprefix("seller:")))
                    except ValueError:
                        continue
            if seller_ids:
                clauses.append(and_(
                    AdminOperation.action == "SELLER_RESTRICTION",
                    AdminOperation.entity_id.in_(seller_ids),
                    reviewer,
                ))
    return or_(*clauses)


def _if_match_version(value: str) -> int:
    raw = value.strip().strip('"')
    if raw.startswith("v"):
        raw = raw[1:]
    try:
        result = int(raw)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "INVALID_IF_MATCH", "message": "If-Match must contain the resource version"}) from exc
    if result < 1:
        raise HTTPException(status_code=422, detail={"code": "INVALID_IF_MATCH", "message": "If-Match version must be positive"})
    return result


def _profile(principal: StaffPrincipal, grants: list[StaffRoleGrant]) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    active = [grant for grant in grants if grant.expires_at is None or grant.expires_at > now]
    roles = sorted({grant.role for grant in active if not grant.role.startswith("permission:")})
    permissions: set[str] = set()
    for grant in active:
        if grant.scope_key == "global":
            allowed = set(ROLE_PERMISSIONS.get(grant.role, ())) if not grant.role.startswith("permission:") else {grant.role.removeprefix("permission:")}
            permissions.update(allowed)
        elif grant.scope_key.startswith("seller:"):
            allowed = set(ROLE_PERMISSIONS.get(grant.role, ())) if not grant.role.startswith("permission:") else {grant.role.removeprefix("permission:")}
            permissions.update(allowed & SELLER_SCOPED_PERMISSIONS)
    return {
        "staff_id": principal.id,
        "oidc_issuer": principal.oidc_issuer,
        "display_name": None,
        "roles": roles,
        "permissions": sorted(permissions),
        "status": principal.status,
        "version": principal.version,
        "grants": [
            {
                "permission": grant.role.removeprefix("permission:") if grant.role.startswith("permission:") else None,
                "grant_id": grant.id,
                "role": None if grant.role.startswith("permission:") else grant.role,
                "scope": grant.scope_key,
                "expires_at": grant.expires_at,
                "granted_by": grant.granted_by,
            }
            for grant in active
        ],
    }


def _operation_response(operation: AdminOperation, request_id: str) -> AdminOperationResponse:
    return AdminOperationResponse(
        operation_id=operation.id,
        status=operation.status,
        resource_id=operation.entity_id,
        request_id=request_id,
        updated_at=operation.updated_at,
        version=operation.version,
    )


def _safe_review_values(source: object, keys: tuple[str, ...]) -> dict[str, str | int | bool]:
    if not isinstance(source, dict):
        return {}
    result: dict[str, str | int | bool] = {}
    for key in keys:
        value = source.get(key)
        if isinstance(value, str) and len(value) <= 256:
            result[key] = value
        elif type(value) in {int, bool}:
            result[key] = value
    return result


def _operation_review_summary(operation: AdminOperation) -> tuple[dict[str, str | int | bool | list[str]], bool]:
    payload = operation.payload if isinstance(operation.payload, dict) else {}
    action = operation.action
    nested = payload.get("command_payload")
    summary: dict[str, str | int | bool | list[str]] = {}
    approval_supported = action in ACTION_APPROVAL_PERMISSIONS or action in TAXONOMY_ACTIONS
    if action == "STAFF_PERMISSION_GRANT":
        summary = _safe_review_values(payload, ("permission", "scope", "expires_at", "expected_staff_version"))
    elif action == "STAFF_PERMISSION_REVOKE":
        role = payload.get("role")
        if isinstance(role, str) and role.startswith("permission:"):
            summary["permission"] = role.removeprefix("permission:")
        summary.update(_safe_review_values(payload, ("scope_key", "expected_staff_version")))
    elif action == "STAFF_SESSION_REVOKE":
        summary = {"effect": "revoke all sessions for this staff principal"}
    elif action in {"BLOCKING_REASON_CREATE", "BLOCKING_REASON_UPDATE"}:
        summary = _safe_review_values(payload, ("code", "title", "description", "severity", "active"))
        if isinstance(payload.get("description"), str) and len(payload["description"]) > 256:
            approval_supported = False
    elif action == "BLOCKING_REASON_ARCHIVE":
        summary = {"effect": "archive blocking reason"}
    elif action == "POLICY_CREATE":
        summary.update(_safe_review_values(payload, ("code",)))
        rules = payload.get("rules")
        if isinstance(rules, dict):
            summary.update(_safe_review_values(rules, ("expected_current_version",)))
            values = rules.get("values")
            if isinstance(values, dict):
                summary.update(_safe_review_values(values, (
                    "moderation_claim_ttl_seconds", "complaint_case_sla_seconds",
                    "admin_session_idle_ttl_seconds", "admin_session_absolute_ttl_seconds",
                    "admin_step_up_max_age_seconds", "moderation_outbox_poll_interval_seconds",
                )))
    elif action == "POLICY_PUBLISH":
        summary = _safe_review_values(payload, ("expected_policy_version", "impact_hash"))
    elif action == "OUTBOX_RETRY":
        summary = _safe_review_values(payload, ("expected_status", "expected_attempts"))
    elif action == "COMPLAINT_ACTION":
        summary = _safe_review_values(payload, ("action", "expected_version"))
    elif action == "SELLER_RESTRICTION":
        summary = _safe_review_values(nested, ("action", "effective_until"))
        summary.update(_safe_review_values(payload, ("expected_version",)))
        if isinstance(nested, dict) and isinstance(nested.get("comment"), str) and nested["comment"].strip():
            approval_supported = False
    elif action == "PRODUCT_SAFETY_HOLD":
        summary = _safe_review_values(nested, ("expires_at", "reason_code"))
        summary.update(_safe_review_values(payload, ("expected_version", "hold_limit_seconds")))
    elif action in {"CATEGORY_CREATE", "CATEGORY_UPDATE"}:
        summary = _safe_review_values(nested, ("parent_id", "code", "slug", "name", "description", "sort_order", "seo_title"))
        summary.update(_safe_review_values(payload, ("expected_version",)))
        if isinstance(nested, dict) and any(isinstance(nested.get(key), str) and len(nested[key]) > 256 for key in ("name", "description", "seo_title")):
            approval_supported = False
    elif action == "CATEGORY_MOVE":
        summary = _safe_review_values(nested, ("new_parent_id", "position", "impact_hash"))
        summary.update(_safe_review_values(payload, ("expected_version",)))
    elif action in {"CATEGORY_ARCHIVE", "CATEGORY_PUBLISH"}:
        summary = _safe_review_values(payload, ("expected_version",))
        summary.update(_safe_review_values(nested, ("impact_hash",)))
    elif action in {"ATTRIBUTE_CREATE", "ATTRIBUTE_UPDATE"}:
        attribute = nested.get("attribute") if isinstance(nested, dict) else None
        summary = _safe_review_values(attribute, ("code", "name", "data_type", "unit", "required", "filterable", "searchable", "comparable", "variant_dimension", "pii"))
        summary.update(_safe_review_values(nested, ("draft_action",)))
        summary.update(_safe_review_values(payload, ("expected_version",)))
        constraints = attribute.get("constraints") if isinstance(attribute, dict) else None
        if constraints is not None:
            encoded_constraints = json.dumps(constraints, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            if len(encoded_constraints) <= 1000:
                summary["constraints"] = encoded_constraints
            else:
                approval_supported = False
        if isinstance(attribute, dict) and any(isinstance(attribute.get(key), str) and len(attribute[key]) > 256 for key in ("name", "unit")):
            approval_supported = False
    elif action == "ATTRIBUTE_RULES_PUBLISH":
        summary = _safe_review_values(nested, ("schema_version",))
        rules = nested.get("rules") if isinstance(nested, dict) else None
        if isinstance(rules, list):
            summary["rule_count"] = len(rules)
            rule_preview = [
                f"{item.get('attribute_id')}: required={item.get('required')}, filterable={item.get('filterable')}, variant_dimension={item.get('variant_dimension')}"
                for item in rules[:100] if isinstance(item, dict)
            ]
            summary["rules"] = rule_preview
            if len(rules) > 100:
                summary["rules_truncated"] = True
                approval_supported = False
            if any(isinstance(item, dict) and item.get("condition") for item in rules):
                approval_supported = False
    elif action in {"BRAND_CREATE", "BRAND_UPDATE"}:
        brand = nested.get("brand") if isinstance(nested, dict) else None
        summary = _safe_review_values(brand, ("name", "aliases", "evidence_ref"))
        summary.update(_safe_review_values(nested, ("draft_action",)))
        summary.update(_safe_review_values(payload, ("expected_version",)))
        if isinstance(brand, dict) and (len(json.dumps(brand, ensure_ascii=False)) > 4000 or len(brand.get("aliases", [])) > 100):
            approval_supported = False
    elif action == "BRAND_VERIFY":
        summary = _safe_review_values(nested, ("evidence_ref",))
        summary.update(_safe_review_values(payload, ("expected_version",)))
    elif action == "BRAND_MERGE":
        summary = _safe_review_values(nested, ("target_brand_id", "impact_hash", "reason_code"))
        summary.update(_safe_review_values(payload, ("expected_version",)))
    if action == "COMPLAINT_ACTION" and isinstance(payload.get("comment"), str) and payload["comment"].strip():
        approval_supported = False
    if action == "PRODUCT_SAFETY_HOLD" and isinstance(nested, dict) and isinstance(nested.get("comment"), str) and nested["comment"].strip():
        approval_supported = False
    return summary, approval_supported


def _operation_review_response(operation: AdminOperation, request_id: str) -> OperationReviewResponse:
    summary, approval_supported = _operation_review_summary(operation)
    return OperationReviewResponse(
        operation_id=operation.id,
        request_id=request_id,
        action=operation.action,
        status=operation.status,
        entity_type=operation.entity_type,
        resource_id=operation.entity_id,
        requested_by_staff_id=operation.requested_by,
        approved_by_staff_id=operation.approved_by,
        cancelled_by_staff_id=operation.cancelled_by,
        reason_code=operation.reason_code,
        created_at=operation.created_at,
        updated_at=operation.updated_at,
        version=operation.version,
        summary=summary,
        approval_supported=approval_supported,
    )


def _audit(
    db: AsyncSession,
    actor_id: UUID,
    action: str,
    entity_type: str,
    entity_id: UUID,
    details: dict[str, object],
) -> None:
    db.add(AuditLog(
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details,
        created_at=datetime.now(timezone.utc),
    ))


@router.get("/admin/v1/me", response_model=PrincipalResponse, response_model_exclude_none=True)
async def get_me(current: SimpleNamespace = Depends(require_permission("session.read"))) -> dict[str, object]:
    return {
        "staff_id": current.id,
        "roles": sorted(current.roles),
        "permissions": sorted(current.permissions),
        "mfa_verified": bool(current.mfa_verified),
        "session_expires_at": current.session_expires_at,
    }


@router.get("/admin/v1/staff", response_model=StaffPageResponse, response_model_exclude_none=True)
async def list_staff(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = Query(None, max_length=1024),
    actor: SimpleNamespace = Depends(require_permission("iam.read")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    position = decode_cursor(cursor, datetime_cursor, UUID)
    query = select(StaffPrincipal)
    if position is not None:
        created_at, staff_id = position
        query = query.where(or_(
            StaffPrincipal.created_at > created_at,
            and_(StaffPrincipal.created_at == created_at, StaffPrincipal.id > staff_id),
        ))
    principals = list((await db.scalars(
        query.order_by(StaffPrincipal.created_at, StaffPrincipal.id).limit(limit + 1)
    )).all())
    has_more = len(principals) > limit
    principals = principals[:limit]
    grant_rows = (await db.scalars(
        select(StaffRoleGrant)
        .where(StaffRoleGrant.principal_id.in_([item.id for item in principals]))
        .order_by(StaffRoleGrant.principal_id, StaffRoleGrant.role, StaffRoleGrant.scope_key, StaffRoleGrant.id)
    )).all() if principals else []
    by_principal: dict[UUID, list[StaffRoleGrant]] = {}
    for grant in grant_rows:
        by_principal.setdefault(grant.principal_id, []).append(grant)
    next_cursor = encode_cursor(principals[-1].created_at, principals[-1].id) if has_more and principals else None
    result = {"items": [_profile(item, by_principal.get(item.id, [])) for item in principals], "page": {"has_more": has_more, "next_cursor": next_cursor}}
    db.add(AuditLog(
        actor_id=actor.id,
        action="STAFF_LIST_READ",
        entity_type="staff_collection",
        entity_id=actor.id,
        details={"request_id": getattr(request.state, "request_id", None), "returned_count": len(principals), "has_more": has_more},
        created_at=datetime.now(timezone.utc),
    ))
    await db.commit()
    return result


@router.get("/admin/v1/staff/{staff_id}", response_model=StaffProfileResponse, response_model_exclude_none=True)
async def get_staff(
    staff_id: UUID,
    request: Request,
    actor: SimpleNamespace = Depends(require_permission("iam.read")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    principal = await db.get(StaffPrincipal, staff_id)
    if principal is None:
        raise HTTPException(status_code=404, detail={"code": "STAFF_NOT_FOUND", "message": "Staff principal not found"})
    grants = list((await db.scalars(
        select(StaffRoleGrant)
        .where(StaffRoleGrant.principal_id == staff_id)
        .order_by(StaffRoleGrant.role, StaffRoleGrant.scope_key, StaffRoleGrant.id)
    )).all())
    result = _profile(principal, grants)
    db.add(AuditLog(
        actor_id=actor.id,
        action="STAFF_PROFILE_READ",
        entity_type="staff",
        entity_id=staff_id,
        details={"request_id": getattr(request.state, "request_id", None)},
        created_at=datetime.now(timezone.utc),
    ))
    await db.commit()
    return result


@router.post("/admin/v1/staff/{staff_id}/grants", response_model=AdminOperationResponse, status_code=202)
async def propose_permission_grant(
    staff_id: UUID,
    data: PermissionChange,
    request: Request,
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    if_match: str = Header(alias="If-Match"),
    current: SimpleNamespace = Depends(require_permission("iam.grant")),
    db: AsyncSession = Depends(get_db),
) -> AdminOperationResponse:
    if data.staff_id != staff_id:
        raise HTTPException(status_code=422, detail={"code": "STAFF_ID_MISMATCH", "message": "Body staff_id must match the path"})
    if data.permission not in PERMISSION_CODES:
        raise HTTPException(status_code=422, detail={"code": "UNKNOWN_PERMISSION", "message": "Permission is not in the Admin permission registry"})
    if data.scope != "global" and data.permission not in SELLER_SCOPED_PERMISSIONS:
        raise HTTPException(status_code=422, detail={"code": "UNSUPPORTED_PERMISSION_SCOPE", "message": "This permission cannot be restricted to a seller scope"})
    if data.expires_at is not None and data.expires_at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=422, detail={"code": "INVALID_EXPIRY", "message": "Permission expiry must be in the future"})
    version = _if_match_version(if_match)
    request_body = data.model_dump(mode="json")
    # Keep the established digest shape so retries of pre-upgrade grant
    # proposals continue to resolve to their existing operation receipt.
    request_hash = hashlib.sha256(json.dumps({"staff_id": str(staff_id), "body": request_body, "version": version}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    prior = await db.scalar(select(AdminOperation).where(
        AdminOperation.requested_by == current.id,
        AdminOperation.idempotency_key == str(idempotency_key),
    ))
    if prior is not None:
        if prior.action != "STAFF_PERMISSION_GRANT" or prior.entity_id != staff_id or not hmac.compare_digest(prior.request_hash, request_hash):
            raise HTTPException(status_code=409, detail={"code": "IDEMPOTENCY_KEY_REUSED", "message": "Idempotency key was used for a different operation"})
        return _operation_response(prior, getattr(getattr(request, "state", None), "request_id", None))
    target = await db.scalar(select(StaffPrincipal).where(StaffPrincipal.id == staff_id).with_for_update())
    if target is None:
        raise HTTPException(status_code=404, detail={"code": "STAFF_NOT_FOUND", "message": "Staff principal not found"})
    if target.status != "ACTIVE":
        raise HTTPException(status_code=409, detail={"code": "STAFF_INACTIVE", "message": "Cannot grant permissions to inactive staff"})
    if current.id == staff_id:
        raise HTTPException(status_code=403, detail={"code": "SELF_GRANT_FORBIDDEN", "message": "Staff cannot propose a permission grant for themselves"})
    if target.version != version:
        raise HTTPException(status_code=412, detail={"code": "VERSION_MISMATCH", "message": "Staff permissions changed; reload before proposing"})
    operation = AdminOperation(
        action="STAFF_PERMISSION_GRANT",
        entity_type="staff",
        entity_id=staff_id,
        payload={**request_body, "expected_staff_version": version},
        idempotency_key=str(idempotency_key),
        request_hash=request_hash,
        requested_by=current.id,
        reason_code=data.reason_code,
        status="WAITING_APPROVAL",
        version=1,
        updated_at=datetime.now(timezone.utc),
    )
    db.add(operation)
    _audit(db, current.id, "STAFF_PERMISSION_GRANT_PROPOSED", "staff", staff_id, {
        "operation_id": str(operation.id), "permission": data.permission, "scope": data.scope,
        "reason_code": data.reason_code,
    })
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        prior = await db.scalar(select(AdminOperation).where(
            AdminOperation.requested_by == current.id,
            AdminOperation.idempotency_key == str(idempotency_key),
        ))
        if prior is None or prior.action != "STAFF_PERMISSION_GRANT" or prior.entity_id != staff_id or not hmac.compare_digest(prior.request_hash, request_hash):
            raise HTTPException(status_code=409, detail={"code": "IDEMPOTENCY_KEY_REUSED", "message": "Idempotency key conflicts with another operation"})
        operation = prior
    return _operation_response(operation, getattr(getattr(request, "state", None), "request_id", None))


@router.post("/admin/v1/staff/{staff_id}/grants/{grant_id}/revoke", response_model=AdminOperationResponse, status_code=202)
async def propose_permission_grant_revocation(
    staff_id: UUID,
    grant_id: UUID,
    data: PermissionGrantRevocation,
    request: Request,
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    if_match: str = Header(alias="If-Match"),
    current: SimpleNamespace = Depends(require_permission("iam.revoke")),
    db: AsyncSession = Depends(get_db),
) -> AdminOperationResponse:
    version = _if_match_version(if_match)
    if current.id == staff_id:
        raise HTTPException(status_code=403, detail={"code": "SELF_REVOCATION_FORBIDDEN", "message": "Staff cannot propose revocation of their own grant"})
    request_hash = hashlib.sha256(json.dumps({
        "action": "STAFF_PERMISSION_REVOKE", "staff_id": str(staff_id), "grant_id": str(grant_id),
        "reason_code": data.reason_code, "expected_staff_version": version,
    }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    prior = await db.scalar(select(AdminOperation).where(
        AdminOperation.requested_by == current.id,
        AdminOperation.idempotency_key == str(idempotency_key),
    ))
    if prior is not None:
        if prior.action != "STAFF_PERMISSION_REVOKE" or not hmac.compare_digest(prior.request_hash, request_hash):
            raise HTTPException(status_code=409, detail={"code": "IDEMPOTENCY_KEY_REUSED", "message": "Idempotency key was used for a different operation"})
        return _operation_response(prior, getattr(getattr(request, "state", None), "request_id", None))

    principal = await db.scalar(select(StaffPrincipal).where(StaffPrincipal.id == staff_id).with_for_update())
    if principal is None:
        raise HTTPException(status_code=404, detail={"code": "STAFF_NOT_FOUND", "message": "Staff principal not found"})
    if principal.version != version:
        raise HTTPException(status_code=412, detail={"code": "STAFF_VERSION_MISMATCH", "message": "Staff permissions changed; reload before proposing revocation"})
    grant = await db.scalar(select(StaffRoleGrant).where(
        StaffRoleGrant.id == grant_id,
        StaffRoleGrant.principal_id == staff_id,
    ).with_for_update())
    now = datetime.now(timezone.utc)
    if grant is None:
        raise HTTPException(status_code=404, detail={"code": "GRANT_NOT_FOUND", "message": "Permission grant not found"})
    if not grant.role.startswith("permission:"):
        raise HTTPException(status_code=409, detail={"code": "ROLE_GRANT_REVOCATION_UNSUPPORTED", "message": "Only explicit permission grants can be revoked through this endpoint"})
    if grant.expires_at is not None and grant.expires_at <= now:
        raise HTTPException(status_code=409, detail={"code": "GRANT_NOT_ACTIVE", "message": "Permission grant is already inactive"})

    operation = AdminOperation(
        action="STAFF_PERMISSION_REVOKE", entity_type="staff", entity_id=staff_id,
        payload={
            "grant_id": str(grant.id), "role": grant.role, "scope_key": grant.scope_key,
            "expected_staff_version": version,
        },
        idempotency_key=str(idempotency_key), request_hash=request_hash,
        requested_by=current.id, reason_code=data.reason_code,
        status="WAITING_APPROVAL", version=1, updated_at=now,
    )
    db.add(operation)
    _audit(db, current.id, "STAFF_PERMISSION_REVOKE_PROPOSED", "staff", staff_id, {
        "operation_id": str(operation.id), "grant_id": str(grant.id),
        "permission": grant.role.removeprefix("permission:"),
        "scope": grant.scope_key, "reason_code": data.reason_code,
    })
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        prior = await db.scalar(select(AdminOperation).where(
            AdminOperation.requested_by == current.id,
            AdminOperation.idempotency_key == str(idempotency_key),
        ))
        if prior is None or prior.action != "STAFF_PERMISSION_REVOKE" or not hmac.compare_digest(prior.request_hash, request_hash):
            raise HTTPException(status_code=409, detail={"code": "IDEMPOTENCY_KEY_REUSED", "message": "Idempotency key conflicts with another operation"}) from exc
        operation = prior
    return _operation_response(operation, getattr(getattr(request, "state", None), "request_id", None))


@router.get("/admin/v1/operations", response_model=OperationReviewPageResponse, response_model_exclude_none=True)
async def list_operations(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = Query(None, max_length=1024),
    actor: SimpleNamespace = Depends(require_permission("operations.read")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    position = decode_cursor(cursor, datetime_cursor, UUID)
    visibility = [AdminOperation.requested_by == actor.id]
    reviewable = _reviewable_operation_filter(actor)
    if reviewable is not None:
        visibility.append(reviewable)
    visibility.append(_reviewed_operation_filter(actor))
    query = select(AdminOperation).where(or_(*visibility))
    if position is not None:
        created_at, operation_id = position
        query = query.where(or_(
            AdminOperation.created_at < created_at,
            and_(AdminOperation.created_at == created_at, AdminOperation.id < operation_id),
        ))
    rows = list((await db.scalars(
        query.order_by(AdminOperation.created_at.desc(), AdminOperation.id.desc()).limit(limit + 1)
    )).all())
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = encode_cursor(rows[-1].created_at, rows[-1].id) if has_more and rows else None
    request_id = str(request.state.request_id)
    response = {"items": [_operation_review_response(item, request_id).model_dump(mode="json") for item in rows], "page": {"has_more": has_more, "next_cursor": next_cursor}}
    db.add(AuditLog(
        actor_id=actor.id,
        action="ADMIN_OPERATIONS_LIST_READ",
        entity_type="admin_operation_collection",
        entity_id=actor.id,
        details={"returned_count": len(rows), "has_more": has_more},
        created_at=datetime.now(timezone.utc),
    ))
    await db.commit()
    return response


@router.get(
    "/admin/v1/operations/{operation_id}",
    response_model=OperationReviewResponse,
    responses={200: {"headers": {"ETag": {"description": "Current operation version", "schema": {"type": "string"}}}}},
)
async def get_operation(
    operation_id: UUID,
    request: Request,
    response: Response,
    actor: SimpleNamespace = Depends(require_permission("operations.read")),
    db: AsyncSession = Depends(get_db),
) -> OperationReviewResponse:
    operation = await db.get(AdminOperation, operation_id)
    if operation is None or not _operation_visible(operation, actor):
        raise HTTPException(status_code=404, detail={"code": "OPERATION_NOT_FOUND", "message": "Operation not found"})
    response.headers["ETag"] = f'"{operation.version}"'
    result = _operation_review_response(operation, str(request.state.request_id))
    db.add(AuditLog(
        actor_id=actor.id,
        action="ADMIN_OPERATION_READ",
        entity_type="admin_operation",
        entity_id=operation.id,
        details={"action": operation.action, "status": operation.status},
        created_at=datetime.now(timezone.utc),
    ))
    await db.commit()
    return result


@router.post("/admin/v1/operations/{operation_id}/approve", response_model=AdminOperationResponse, status_code=202)
async def approve_operation(
    operation_id: UUID,
    data: ReasonAction,
    request: Request,
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    if_match: str = Header(alias="If-Match"),
    current: SimpleNamespace = Depends(get_current_moderator),
    db: AsyncSession = Depends(get_db),
) -> AdminOperationResponse:
    approval_permissions = {
        "operations.approve",
        "iam.grant",
        "iam.revoke",
        "policy.reason.write",
        "policy.write",
        "policy.publish",
        "operations.events.retry",
        "appeal.decide",
        "complaint.decide",
        "products.safety_hold",
        "taxonomy.category.publish",
        "taxonomy.attribute.publish",
        "taxonomy.brand.publish",
        "seller.restrict",
        "*",
    }
    if not (approval_permissions & set(current.permissions)):
        raise HTTPException(status_code=403, detail={"code": "PERMISSION_DENIED", "message": "Operation approval permission is required"})
    require_recent_step_up(current)
    expected_version = _if_match_version(if_match)
    approval_hash = hashlib.sha256(json.dumps({
        "operation_id": str(operation_id), "actor": str(current.id),
        "reason_code": data.reason_code, "comment": data.comment, "version": expected_version,
    }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    operation = await db.scalar(select(AdminOperation).where(AdminOperation.id == operation_id).with_for_update())
    if operation is None:
        raise HTTPException(status_code=404, detail={"code": "OPERATION_NOT_FOUND", "message": "Operation not found"})
    if operation.action not in ACTION_APPROVAL_PERMISSIONS and operation.action not in TAXONOMY_ACTIONS:
        raise HTTPException(status_code=409, detail={"code": "OPERATION_ACTION_NOT_REVIEWABLE", "message": "This operation action is not supported by the maker-checker workflow"})
    taxonomy_actions = TAXONOMY_ACTIONS
    required_approval_permissions = _approval_permission(operation.action)
    if "*" not in current.permissions and not (required_approval_permissions & set(current.permissions)):
        raise HTTPException(status_code=403, detail={"code": "PERMISSION_DENIED", "message": "Permission to approve this operation is required"})
    if operation.action == "APPEAL_DECISION":
        raise HTTPException(
            status_code=503,
            detail={
                "code": "NOTICE_DELIVERY_NOT_CONFIGURED",
                "message": "Appeal decisions require a configured case-notice delivery service",
            },
        )
    if operation.action in taxonomy_actions:
        if operation.action in {"ATTRIBUTE_RULES_PUBLISH", "ATTRIBUTE_CREATE", "ATTRIBUTE_UPDATE"}:
            required_taxonomy_permission = "taxonomy.attribute.publish"
        elif operation.action in {"BRAND_CREATE", "BRAND_UPDATE", "BRAND_VERIFY", "BRAND_MERGE"}:
            required_taxonomy_permission = "taxonomy.brand.publish"
        else:
            required_taxonomy_permission = "taxonomy.category.publish"
        if required_taxonomy_permission not in current.permissions and "*" not in current.permissions:
            raise HTTPException(status_code=403, detail={"code": "PERMISSION_DENIED", "message": "Taxonomy approval permission is required"})
    elif operation.action == "SELLER_RESTRICTION":
        if "seller.restrict" not in current.permissions and "*" not in current.permissions:
            raise HTTPException(status_code=403, detail={"code": "PERMISSION_DENIED", "message": "Seller restriction approval permission is required"})
        if (
            "*" not in current.permissions
            and "*" not in current.permission_scopes.get("seller.restrict", set())
        ):
            seller_scope = f"seller:{operation.entity_id}"
            if seller_scope not in current.permission_scopes.get("seller.restrict", set()):
                raise HTTPException(status_code=403, detail={"code": "SCOPE_DENIED", "message": "Seller restriction is outside the granted seller scope"})
    elif operation.action == "STAFF_PERMISSION_REVOKE":
        if "iam.revoke" not in current.permissions and "*" not in current.permissions:
            raise HTTPException(status_code=403, detail={"code": "PERMISSION_DENIED", "message": "Permission revocation approval permission is required"})
    if operation.approval_key is not None:
        if operation.approval_key == str(idempotency_key) and operation.approved_by == current.id and hmac.compare_digest(operation.approval_hash or "", approval_hash):
            return _operation_response(operation, getattr(getattr(request, "state", None), "request_id", None))
        raise HTTPException(status_code=409, detail={"code": "OPERATION_ALREADY_REVIEWED", "message": "Operation already has an approval decision"})
    if operation.status != "WAITING_APPROVAL":
        raise HTTPException(status_code=409, detail={"code": "OPERATION_NOT_REVIEWABLE", "message": "Operation is not waiting for approval"})
    if operation.requested_by == current.id:
        _audit(
            db,
            current.id,
            "ADMIN_MAKER_CHECKER_VIOLATION",
            "admin_operation",
            operation.id,
            {"action": operation.action, "status_code": 403},
        )
        try:
            await db.commit()
        except Exception as exc:
            await db.rollback()
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "AUTH_AUDIT_UNAVAILABLE",
                    "message": "Maker-checker denial could not be recorded",
                },
            ) from exc
        raise HTTPException(status_code=403, detail={"code": "MAKER_CHECKER_VIOLATION", "message": "The proposer cannot approve their own operation"})
    if operation.version != expected_version:
        raise HTTPException(status_code=412, detail={"code": "VERSION_MISMATCH", "message": "Operation changed; reload before approval"})
    if operation.action in {"STAFF_PERMISSION_GRANT", "STAFF_PERMISSION_REVOKE", "STAFF_SESSION_REVOKE", "COMPLAINT_ACTION", "BLOCKING_REASON_ARCHIVE", "POLICY_CREATE", "POLICY_PUBLISH", "OUTBOX_RETRY", "APPEAL_DECISION", "PRODUCT_SAFETY_HOLD", *taxonomy_actions, "SELLER_RESTRICTION"} and data.reason_code != operation.reason_code:
        raise HTTPException(status_code=409, detail={"code": "REASON_CODE_MISMATCH", "message": "Approval reason must match the proposed operation reason"})
    payload = operation.payload
    audit_entity_type = operation.entity_type
    audit_entity_id = operation.entity_id
    if operation.action == "STAFF_PERMISSION_GRANT":
        permission = str(payload["permission"])
        scope = str(payload.get("scope") or "global")
        if permission not in PERMISSION_CODES:
            raise HTTPException(status_code=409, detail={"code": "UNKNOWN_PERMISSION", "message": "Stored permission is not in the Admin permission registry"})
        if scope != "global":
            if permission not in SELLER_SCOPED_PERMISSIONS:
                raise HTTPException(status_code=409, detail={"code": "UNSUPPORTED_PERMISSION_SCOPE", "message": "Stored permission cannot be restricted to a seller scope"})
            if not scope.startswith("seller:"):
                raise HTTPException(status_code=409, detail={"code": "INVALID_PERMISSION_SCOPE", "message": "Stored seller scope is invalid"})
            try:
                scope = f"seller:{UUID(scope.removeprefix('seller:'))}"
            except ValueError as exc:
                raise HTTPException(status_code=409, detail={"code": "INVALID_PERMISSION_SCOPE", "message": "Stored seller scope is invalid"}) from exc
        principal = await db.scalar(select(StaffPrincipal).where(StaffPrincipal.id == operation.entity_id).with_for_update())
        if principal is None or principal.status != "ACTIVE":
            raise HTTPException(status_code=409, detail={"code": "STAFF_INACTIVE", "message": "Target staff is unavailable"})
        if principal.id == current.id:
            raise HTTPException(status_code=403, detail={"code": "SELF_GRANT_FORBIDDEN", "message": "Staff cannot approve a permission grant for themselves"})
        if principal.version != int(payload["expected_staff_version"]):
            raise HTTPException(status_code=412, detail={"code": "STAFF_VERSION_MISMATCH", "message": "Target staff permissions changed after the grant was proposed"})
        expires_at_raw = payload.get("expires_at")
        try:
            expires_at = datetime.fromisoformat(str(expires_at_raw)) if expires_at_raw else None
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=409, detail={"code": "INVALID_GRANT_EXPIRY", "message": "Stored permission expiry is invalid"}) from exc
        if expires_at is not None:
            if expires_at.tzinfo is None or expires_at.utcoffset() is None:
                raise HTTPException(status_code=409, detail={"code": "INVALID_GRANT_EXPIRY", "message": "Stored permission expiry must include a timezone"})
            if expires_at <= datetime.now(timezone.utc):
                raise HTTPException(status_code=409, detail={"code": "GRANT_EXPIRED", "message": "Proposed permission grant has expired"})
        grant_code = f"permission:{permission}"
        existing_grant = await db.scalar(select(StaffRoleGrant).where(
            StaffRoleGrant.principal_id == principal.id,
            StaffRoleGrant.role == grant_code,
            StaffRoleGrant.scope_key == scope,
        ).with_for_update())
        if existing_grant is not None and (existing_grant.expires_at is None or existing_grant.expires_at > datetime.now(timezone.utc)):
            raise HTTPException(status_code=409, detail={"code": "GRANT_ALREADY_EXISTS", "message": "An active grant already exists for this permission and scope"})
        if existing_grant is not None:
            existing_grant.granted_by = current.id
            existing_grant.expires_at = expires_at
        else:
            db.add(StaffRoleGrant(
                principal_id=principal.id,
                role=grant_code,
                scope_key=scope,
                granted_by=current.id,
                expires_at=expires_at,
            ))
        principal.version += 1
    elif operation.action == "STAFF_PERMISSION_REVOKE":
        if "iam.revoke" not in current.permissions and "*" not in current.permissions:
            raise HTTPException(status_code=403, detail={"code": "PERMISSION_DENIED", "message": "Permission revocation approval permission is required"})
        principal = await db.scalar(select(StaffPrincipal).where(StaffPrincipal.id == operation.entity_id).with_for_update())
        if principal is None or principal.status != "ACTIVE":
            raise HTTPException(status_code=409, detail={"code": "STAFF_INACTIVE", "message": "Target staff is unavailable"})
        if principal.version != int(payload["expected_staff_version"]):
            raise HTTPException(status_code=412, detail={"code": "STAFF_VERSION_MISMATCH", "message": "Target staff permissions changed after revocation was proposed"})
        grant = await db.scalar(select(StaffRoleGrant).where(
            StaffRoleGrant.id == UUID(str(payload["grant_id"])),
            StaffRoleGrant.principal_id == principal.id,
        ).with_for_update())
        if grant is None or grant.role != str(payload["role"]) or grant.scope_key != str(payload["scope_key"]):
            raise HTTPException(status_code=409, detail={"code": "GRANT_CHANGED", "message": "Permission grant changed after revocation was proposed"})
        now = datetime.now(timezone.utc)
        if grant.expires_at is not None and grant.expires_at <= now:
            raise HTTPException(status_code=409, detail={"code": "GRANT_NOT_ACTIVE", "message": "Permission grant is already inactive"})
        grant.expires_at = now
        principal.version += 1
        audit_entity_type = "staff"
    elif operation.action in {"BLOCKING_REASON_CREATE", "BLOCKING_REASON_UPDATE", "BLOCKING_REASON_ARCHIVE"}:
        if "policy.reason.write" not in current.permissions and "*" not in current.permissions:
            raise HTTPException(status_code=403, detail={"code": "PERMISSION_DENIED", "message": "Reason policy approval permission is required"})
        reason = await db.scalar(select(BlockingReason).where(BlockingReason.id == operation.entity_id).with_for_update())
        if operation.action == "BLOCKING_REASON_CREATE":
            if reason is not None or await db.scalar(select(BlockingReason.id).where(BlockingReason.code == payload["code"])) is not None:
                raise HTTPException(status_code=409, detail={"code": "REASON_CODE_EXISTS", "message": "Blocking reason already exists"})
            severity = str(payload["severity"])
            db.add(BlockingReason(
                id=operation.entity_id,
                code=str(payload["code"]),
                title=str(payload["title"]),
                description=payload.get("description"),
                severity=severity,
                hard_block=severity == "HARD_BLOCK",
                is_active=bool(payload.get("active", True)),
            ))
        else:
            if reason is None:
                raise HTTPException(status_code=404, detail={"code": "REASON_NOT_FOUND", "message": "Blocking reason not found"})
            if reason.version != int(payload["expected_reason_version"]):
                raise HTTPException(status_code=412, detail={"code": "REASON_VERSION_MISMATCH", "message": "Reason changed after this operation was proposed"})
            if operation.action == "BLOCKING_REASON_UPDATE":
                severity = str(payload["severity"])
                reason.code = str(payload["code"])
                reason.title = str(payload["title"])
                if "description" in payload:
                    reason.description = payload["description"]
                reason.severity = severity
                reason.hard_block = severity == "HARD_BLOCK"
                if "active" in payload:
                    reason.is_active = bool(payload["active"])
            else:
                reason.is_active = False
            reason.version += 1
        audit_entity_type = "blocking_reason"
    elif operation.action in {"POLICY_CREATE", "POLICY_PUBLISH"}:
        required_permission = "policy.write" if operation.action == "POLICY_CREATE" else "policy.publish"
        if required_permission not in current.permissions and "*" not in current.permissions:
            raise HTTPException(status_code=403, detail={"code": "PERMISSION_DENIED", "message": "Policy approval permission is required"})
        if operation.action == "POLICY_CREATE":
            policy_code = str(payload["code"])
            await db.execute(select(func.pg_advisory_xact_lock(func.hashtext(policy_code))))
            try:
                runtime_policy = validate_policy_rules(policy_code, payload["rules"])
            except ValueError as exc:
                raise HTTPException(status_code=409, detail={"code": "RUNTIME_POLICY_INVALID", "message": "Stored runtime policy proposal is invalid"}) from exc
            if runtime_policy is not None:
                _, _, expected_current_version = runtime_policy
                active_version = int(await db.scalar(select(func.max(AdminPolicy.version)).where(
                    AdminPolicy.code == policy_code,
                    AdminPolicy.status == "PUBLISHED",
                )) or 0)
                if active_version != expected_current_version:
                    raise HTTPException(status_code=412, detail={"code": "RUNTIME_POLICY_VERSION_MISMATCH", "message": "A different runtime policy was published after this proposal was created"})
            canonical_rules = json.dumps(payload["rules"], sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            content_hash = hashlib.sha256(canonical_rules.encode("utf-8")).hexdigest()
            if not hmac.compare_digest(content_hash, str(payload["content_hash"])):
                raise HTTPException(status_code=409, detail={"code": "POLICY_CONTENT_HASH_INVALID", "message": "Policy payload hash verification failed"})
            latest_version = int(await db.scalar(select(func.max(AdminPolicy.version)).where(AdminPolicy.code == policy_code)) or 0)
            db.add(AdminPolicy(
                id=operation.entity_id,
                code=policy_code,
                version=latest_version + 1,
                status="APPROVED",
                rules=payload["rules"],
                content_hash=content_hash,
                reason_code=str(payload["reason_code"]),
                created_by=operation.requested_by,
                approved_by=current.id,
                updated_at=datetime.now(timezone.utc),
            ))
        else:
            policy = await db.scalar(select(AdminPolicy).where(AdminPolicy.id == operation.entity_id).with_for_update())
            if policy is None or policy.status != "APPROVED":
                raise HTTPException(status_code=409, detail={"code": "POLICY_NOT_APPROVED", "message": "Policy version is not in an approved state"})
            if policy.version != int(payload["expected_policy_version"]) or not hmac.compare_digest(policy.content_hash, str(payload["impact_hash"])):
                raise HTTPException(status_code=412, detail={"code": "POLICY_VERSION_MISMATCH", "message": "Policy content changed after the publish operation was proposed"})
            try:
                runtime_policy = validate_policy_rules(policy.code, policy.rules)
            except ValueError as exc:
                raise HTTPException(status_code=409, detail={"code": "RUNTIME_POLICY_INVALID", "message": "Stored runtime policy is invalid"}) from exc
            if runtime_policy is not None:
                _, _, expected_current_version = runtime_policy
                active_version = int(await db.scalar(select(func.max(AdminPolicy.version)).where(
                    AdminPolicy.code == policy.code,
                    AdminPolicy.status == "PUBLISHED",
                    AdminPolicy.id != policy.id,
                )) or 0)
                if active_version != expected_current_version:
                    raise HTTPException(status_code=412, detail={"code": "RUNTIME_POLICY_VERSION_MISMATCH", "message": "A different runtime policy was published after this proposal was created"})
            claimed_approver = payload.get("approved_by")
            if claimed_approver and str(current.id) != str(claimed_approver):
                raise HTTPException(status_code=409, detail={"code": "APPROVER_MISMATCH", "message": "Only the named independent approver can publish this policy"})
            await db.execute(
                select(AdminPolicy).where(
                    AdminPolicy.code == policy.code,
                    AdminPolicy.status == "PUBLISHED",
                    AdminPolicy.id != policy.id,
                ).with_for_update()
            )
            prior_published = list((await db.scalars(select(AdminPolicy).where(
                AdminPolicy.code == policy.code,
                AdminPolicy.status == "PUBLISHED",
                AdminPolicy.id != policy.id,
            ).with_for_update())).all())
            for prior_policy in prior_published:
                prior_policy.status = "SUPERSEDED"
                prior_policy.updated_at = datetime.now(timezone.utc)
            policy.status = "PUBLISHED"
            policy.effective_at = datetime.now(timezone.utc)
            policy.updated_at = policy.effective_at
            policy.approved_by = current.id
        audit_entity_type = "policy"
    elif operation.action == "OUTBOX_RETRY":
        if "operations.events.retry" not in current.permissions and "*" not in current.permissions:
            raise HTTPException(status_code=403, detail={"code": "PERMISSION_DENIED", "message": "Outbox retry approval permission is required"})
        event = await db.scalar(select(ModerationOutboxEvent).where(
            ModerationOutboxEvent.id == operation.entity_id
        ).with_for_update())
        if event is None:
            raise HTTPException(status_code=404, detail={"code": "EVENT_NOT_FOUND", "message": "Outbox event not found"})
        if event.status != str(payload["expected_status"]) or event.attempts != int(payload["expected_attempts"]):
            raise HTTPException(status_code=409, detail={"code": "EVENT_STATE_CHANGED", "message": "Outbox event changed since the retry was proposed"})
        if event.status not in {"DEAD", "RETRY"}:
            raise HTTPException(status_code=409, detail={"code": "EVENT_NOT_RETRYABLE", "message": "Outbox event is no longer retryable"})
        event.status = "PENDING"
        event.attempts = 0
        event.next_retry_at = datetime.now(timezone.utc)
        event.lease_owner = None
        event.lease_until = None
        audit_entity_type = "outbox_event"
    elif operation.action == "STAFF_SESSION_REVOKE":
        if "iam.revoke" not in current.permissions and "*" not in current.permissions:
            raise HTTPException(status_code=403, detail={"code": "PERMISSION_DENIED", "message": "Session revocation approval permission is required"})
        principal = await db.scalar(select(StaffPrincipal).where(StaffPrincipal.id == operation.entity_id).with_for_update())
        if principal is None:
            raise HTTPException(status_code=404, detail={"code": "STAFF_NOT_FOUND", "message": "Staff principal not found"})
        if principal.id == current.id:
            raise HTTPException(status_code=403, detail={"code": "SELF_APPROVAL_FORBIDDEN", "message": "Staff cannot approve revocation of their own sessions"})
        if principal.version != int(payload["expected_staff_version"]):
            raise HTTPException(status_code=412, detail={"code": "STAFF_VERSION_MISMATCH", "message": "Staff profile changed after the revoke request"})
        principal.sessions_revoked_at = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(seconds=1)
        principal.version += 1
        audit_entity_type = "staff"
    elif operation.action == "COMPLAINT_ACTION":
        if "complaint.decide" not in current.permissions and "*" not in current.permissions:
            raise HTTPException(status_code=403, detail={"code": "PERMISSION_DENIED", "message": "Complaint action approval permission is required"})
        complaint = await db.scalar(select(Complaint).where(Complaint.id == operation.entity_id).with_for_update())
        action = await db.get(ComplaintActionRow, operation.id)
        if complaint is None or action is None:
            raise HTTPException(status_code=404, detail={"code": "COMPLAINT_ACTION_NOT_FOUND", "message": "Complaint action is unavailable"})
        if complaint.version != int(payload["expected_version"]) or action.actor_id != operation.requested_by:
            raise HTTPException(status_code=412, detail={"code": "COMPLAINT_VERSION_MISMATCH", "message": "Complaint changed after the action was proposed"})
        if action.action not in {"TEMP_HOLD", "UNPUBLISH"}:
            raise HTTPException(status_code=409, detail={"code": "COMPLAINT_ACTION_NOT_REVIEWABLE", "message": "Only high-impact complaint actions require approval"})
        complaint.status = "ESCALATED"
        complaint.version += 1
        complaint.updated_at = datetime.now(timezone.utc)
        db.add(ModerationOutboxEvent(
            idempotency_key=f"complaint-action:{operation.id}",
            event_type="COMPLAINT_SAFETY_ACTION",
            payload={
                "complaint_id": str(complaint.id), "entity_type": complaint.entity_type,
                "entity_id": str(complaint.entity_id), "action": action.action,
                "reason_code": action.reason_code, "requested_by": str(action.actor_id),
                "approved_by": str(current.id),
            },
            status="BLOCKED",
            last_error="B2B_SAFETY_ACTION_CONTRACT_UNAVAILABLE",
        ))
        operation.status = "PARTIAL"
        audit_entity_type = "complaint"
    elif operation.action in taxonomy_actions:
        if operation.action in {"ATTRIBUTE_RULES_PUBLISH", "ATTRIBUTE_CREATE", "ATTRIBUTE_UPDATE"}:
            if "taxonomy.attribute.publish" not in current.permissions and "*" not in current.permissions:
                raise HTTPException(status_code=403, detail={"code": "PERMISSION_DENIED", "message": "Attribute schema approval permission is required"})
            command_type = operation.action
        elif operation.action in {"BRAND_CREATE", "BRAND_UPDATE", "BRAND_VERIFY", "BRAND_MERGE"}:
            if "taxonomy.brand.publish" not in current.permissions and "*" not in current.permissions:
                raise HTTPException(status_code=403, detail={"code": "PERMISSION_DENIED", "message": "Brand approval permission is required"})
            command_type = "BRAND_MERGE"
        else:
            if "taxonomy.category.publish" not in current.permissions and "*" not in current.permissions:
                raise HTTPException(status_code=403, detail={"code": "PERMISSION_DENIED", "message": "Taxonomy approval permission is required"})
            command_type = operation.action
        command_id = operation.id
        command = {
            "command_id": str(command_id),
            "command_type": command_type,
            "aggregate_id": str(operation.entity_id),
            "expected_version": int(payload["expected_version"]),
            "payload": payload["command_payload"],
            "requested_by_staff_id": str(operation.requested_by),
            "approved_by_staff_id": str(current.id),
            "reason_code": operation.reason_code,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
        }
        impact_hash = payload["command_payload"].get("impact_hash")
        if isinstance(impact_hash, str):
            command["impact_hash"] = impact_hash
        db.add(ModerationOutboxEvent(
            idempotency_key=f"taxonomy-command:{operation.id}",
            event_type="TAXONOMY_COMMAND",
            payload={"operation_id": str(operation.id), "entity_type": operation.entity_type, "command": command},
        ))
        # Approval authorizes dispatch. The operation becomes APPLIED only
        # after the B2B command receipt confirms its authoritative write.
        operation.status = "QUEUED"
        audit_entity_type = operation.entity_type
    elif operation.action == "SELLER_RESTRICTION":
        command_payload = payload.get("command_payload")
        raw_expected_version = payload.get("expected_version")
        if type(raw_expected_version) is not int or raw_expected_version < 1:
            raise HTTPException(status_code=409, detail={"code": "INVALID_SELLER_RESTRICTION", "message": "Stored seller restriction version is invalid"})
        try:
            restriction = SellerRestrictionInput.model_validate(command_payload)
        except (ValidationError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=409, detail={"code": "INVALID_SELLER_RESTRICTION", "message": "Stored seller restriction command is invalid"}) from exc
        if restriction.reason_code != operation.reason_code:
            raise HTTPException(status_code=409, detail={"code": "INVALID_SELLER_RESTRICTION", "message": "Stored seller restriction reason does not match the operation"})
        command = {
            "command_id": str(operation.id), "command_type": "SELLER_RESTRICTION",
            "aggregate_id": str(operation.entity_id), "expected_version": raw_expected_version,
            "payload": restriction.model_dump(mode="json"), "requested_by_staff_id": str(operation.requested_by),
            "approved_by_staff_id": str(current.id), "reason_code": operation.reason_code,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
        }
        db.add(ModerationOutboxEvent(
            idempotency_key=f"admin-command:{operation.id}", event_type="B2B_COMMAND",
            payload={"operation_id": str(operation.id), "entity_type": "seller", "command": command},
        ))
        operation.status = "QUEUED"
        audit_entity_type = "seller"
    elif operation.action == "PRODUCT_SAFETY_HOLD":
        if "products.safety_hold" not in current.permissions and "*" not in current.permissions:
            raise HTTPException(status_code=403, detail={"code": "PERMISSION_DENIED", "message": "Safety hold approval permission is required"})
        hold_limit_seconds = settings.admin_safety_hold_max_seconds
        stored_hold_limit = payload.get("hold_limit_seconds")
        if type(hold_limit_seconds) is not int or type(stored_hold_limit) is not int or hold_limit_seconds != stored_hold_limit:
            raise HTTPException(status_code=409, detail={"code": "SAFETY_HOLD_POLICY_CHANGED", "message": "The safety-hold limit changed; cancel and re-propose under the current policy"})
        command_payload = payload.get("command_payload")
        raw_expected_version = payload.get("expected_version")
        if type(raw_expected_version) is not int or raw_expected_version < 1:
            raise HTTPException(status_code=409, detail={"code": "INVALID_SAFETY_HOLD", "message": "Stored safety-hold revision is invalid"})
        try:
            hold = HoldInput.model_validate(command_payload)
        except (ValidationError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=409, detail={"code": "INVALID_SAFETY_HOLD", "message": "Stored safety-hold expiry is invalid"}) from exc
        if hold.reason_code != operation.reason_code:
            raise HTTPException(status_code=409, detail={"code": "INVALID_SAFETY_HOLD", "message": "Stored safety-hold reason does not match the operation"})
        expires_at = hold.expires_at
        now = datetime.now(timezone.utc)
        if expires_at.tzinfo is None or expires_at.utcoffset() is None or expires_at <= now:
            raise HTTPException(status_code=409, detail={"code": "SAFETY_HOLD_EXPIRED", "message": "The proposed safety hold has expired"})
        if (expires_at - now).total_seconds() <= hold_limit_seconds:
            raise HTTPException(status_code=409, detail={"code": "SAFETY_HOLD_POLICY_CHANGED", "message": "The hold no longer requires approval under the current policy"})
        command = {
            "command_id": str(operation.id), "command_type": "PRODUCT_SAFETY_HOLD",
            "aggregate_id": str(operation.entity_id), "expected_version": raw_expected_version,
            "payload": hold.model_dump(mode="json"), "requested_by_staff_id": str(operation.requested_by),
            "approved_by_staff_id": str(current.id), "reason_code": operation.reason_code,
            "occurred_at": now.isoformat(),
        }
        db.add(ModerationOutboxEvent(
            idempotency_key=f"admin-command:{operation.id}", event_type="B2B_COMMAND",
            payload={"operation_id": str(operation.id), "entity_type": "product", "command": command},
        ))
        operation.status = "QUEUED"
        audit_entity_type = "product"
    else:
        raise HTTPException(status_code=409, detail={"code": "UNSUPPORTED_OPERATION", "message": "No executor is registered for this operation type"})
    now = datetime.now(timezone.utc)
    if operation.action not in {"APPEAL_DECISION", "COMPLAINT_ACTION", "PRODUCT_SAFETY_HOLD", *taxonomy_actions, "SELLER_RESTRICTION"}:
        operation.status = "APPLIED"
    operation.approved_by = current.id
    operation.approval_key = str(idempotency_key)
    operation.approval_hash = approval_hash
    operation.version += 1
    operation.updated_at = now
    audit_action = f"{operation.action}_APPROVED"
    permission_change_details: dict[str, object] = {}
    if operation.action == "STAFF_PERMISSION_GRANT":
        permission_change_details = {
            "permission": str(payload["permission"]),
            "scope": str(payload.get("scope") or "global"),
        }
    elif operation.action == "STAFF_PERMISSION_REVOKE":
        permission_change_details = {
            "grant_id": str(payload["grant_id"]),
            "permission": str(payload["role"]).removeprefix("permission:"),
            "scope": str(payload["scope_key"]),
        }
    elif operation.action == "PRODUCT_SAFETY_HOLD":
        command_payload = payload.get("command_payload", {})
        permission_change_details = {
            "expires_at": str(command_payload.get("expires_at")) if isinstance(command_payload, dict) else None,
            "hold_limit_seconds": payload.get("hold_limit_seconds"),
            "expected_revision": payload.get("expected_version"),
        }
    _audit(db, current.id, audit_action, audit_entity_type, audit_entity_id, {
        "operation_id": str(operation.id), "requested_by": str(operation.requested_by),
        "reason_code": data.reason_code, "proposer_reason_code": operation.reason_code,
        **permission_change_details,
        **({"original_decision_id": str(payload["original_decision_id"]), "outcome": str(payload["outcome"])} if operation.action == "APPEAL_DECISION" else {}),
        **({"previous_attempts": int(payload["expected_attempts"])} if operation.action == "OUTBOX_RETRY" else {}),
    })
    action_name = operation.action
    operation_payload = operation.payload
    entity_id = operation.entity_id
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        prior = await db.scalar(select(AdminOperation).where(AdminOperation.approval_key == str(idempotency_key)))
        if prior is not None and prior.id == operation_id and prior.approved_by == current.id and hmac.compare_digest(prior.approval_hash or "", approval_hash):
            operation = prior
        else:
            if action_name.startswith("BLOCKING_REASON_") and operation_payload.get("code"):
                conflicting_reason = await db.scalar(select(BlockingReason.id).where(
                    BlockingReason.code == str(operation_payload["code"]),
                    BlockingReason.id != entity_id,
                ))
                if conflicting_reason is not None:
                    raise HTTPException(status_code=409, detail={"code": "REASON_CODE_EXISTS", "message": "Blocking reason code is already in use"}) from exc
            raise HTTPException(status_code=409, detail={"code": "OPERATION_CONFLICT", "message": "Operation could not be applied because its data conflicts with current state"}) from exc
    return _operation_response(operation, getattr(getattr(request, "state", None), "request_id", None))


@router.post("/admin/v1/operations/{operation_id}/cancel", response_model=AdminOperationResponse, status_code=202)
async def cancel_operation(
    operation_id: UUID,
    data: ReasonAction,
    request: Request,
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    if_match: str = Header(alias="If-Match"),
    current: SimpleNamespace = Depends(require_permission("operations.cancel")),
    db: AsyncSession = Depends(get_db),
) -> AdminOperationResponse:
    expected_version = _if_match_version(if_match)
    operation = await db.scalar(select(AdminOperation).where(AdminOperation.id == operation_id).with_for_update())
    if operation is None:
        raise HTTPException(status_code=404, detail={"code": "OPERATION_NOT_FOUND", "message": "Operation not found"})
    cancel_hash = hashlib.sha256(json.dumps({
        "operation_id": str(operation_id), "actor": str(current.id),
        "reason_code": data.reason_code, "comment": data.comment,
        "version": expected_version,
    }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if operation.cancel_key is not None:
        if operation.cancel_key == str(idempotency_key) and operation.cancelled_by == current.id and hmac.compare_digest(operation.cancel_hash or "", cancel_hash):
            return _operation_response(operation, getattr(request.state, "request_id", None))
        raise HTTPException(status_code=409, detail={"code": "OPERATION_ALREADY_REVIEWED", "message": "Operation already has a cancellation decision"})
    if operation.status != "WAITING_APPROVAL":
        raise HTTPException(status_code=409, detail={"code": "OPERATION_NOT_CANCELLABLE", "message": "Only a pending operation can be cancelled"})
    if operation.version != expected_version:
        raise HTTPException(status_code=412, detail={"code": "VERSION_MISMATCH", "message": "Operation changed; reload before cancelling"})
    operation.status = "CANCELLED"
    operation.version += 1
    operation.cancelled_by = current.id
    operation.cancel_key = str(idempotency_key)
    operation.cancel_hash = cancel_hash
    operation.updated_at = datetime.now(timezone.utc)
    _audit(db, current.id, "ADMIN_OPERATION_CANCELLED", operation.entity_type, operation.entity_id, {
        "operation_id": str(operation.id), "reason_code": data.reason_code,
    })
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        prior = await db.scalar(select(AdminOperation).where(AdminOperation.cancel_key == str(idempotency_key)))
        if prior is not None and prior.id == operation_id and prior.cancelled_by == current.id and hmac.compare_digest(prior.cancel_hash or "", cancel_hash):
            operation = prior
        else:
            raise HTTPException(status_code=409, detail={"code": "IDEMPOTENCY_KEY_REUSED", "message": "Cancellation key conflicts with another operation"}) from exc
    return _operation_response(operation, getattr(request.state, "request_id", None))
