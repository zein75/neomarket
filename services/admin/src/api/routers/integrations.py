import hashlib
import hmac
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import require_permission
from src.api.router import AdminAPIRoute
from src.core.config import settings
from src.core.database import get_db
from src.models.audit_log import AuditLog
from src.models.admin_operation import AdminOperation
from src.schemas.admin import AdminOperationResponse, RuntimeSettingsProposalInput
from src.schemas.admin_responses import IntegrationStatusResponse, RuntimeSettingsResponse
from src.services.runtime_settings import (
    POLICY_CODES,
    RuntimeSection,
    active_version,
    effective_values,
    validate_values,
)
from src.api.routers.policies import _propose

router = APIRouter(route_class=AdminAPIRoute, tags=["settings"])


@router.get(
    "/admin/v1/settings/integrations",
    response_model=IntegrationStatusResponse,
    operation_id="GET_admin_v1_settings_integrations",
)
async def get_integration_status(
    current: SimpleNamespace = Depends(require_permission("settings.read")),
    db: AsyncSession = Depends(get_db),
) -> IntegrationStatusResponse:
    oidc_configured = bool(settings.oidc_issuer and settings.oidc_jwks_url and settings.oidc_audience)
    mfa_configured = (
        oidc_configured
        and settings.oidc_mfa_claims_configured
        and bool(settings.oidc_required_amr.strip() or settings.oidc_required_acr.strip())
    )
    step_up_configured = mfa_configured and bool(
        settings.oidc_step_up_required_amr.strip() or settings.oidc_step_up_required_acr.strip()
    )
    items = [
        {
            "key": "identity_provider",
            "status": "CONFIGURED_UNVERIFIED" if oidc_configured else "NOT_CONFIGURED",
            "blocked_actions": [] if oidc_configured else ["admin_sign_in"],
            "detail": "OIDC settings are present; provider reachability is not checked here" if oidc_configured else "OIDC issuer, JWKS URL and audience are required",
        },
        {
            "key": "mfa_step_up",
            "status": "CONFIGURED_UNVERIFIED" if step_up_configured else "NOT_CONFIGURED",
            "blocked_actions": [] if step_up_configured else ["hard_block", "sensitive_approval"],
            "detail": "MFA and step-up claims are configured; provider behavior is not verified here" if step_up_configured else "MFA and step-up claim mappings are required",
        },
        {
            "key": "b2b_admin_api",
            "status": "NOT_CONFIGURED",
            "blocked_actions": ["product_search", "seller_cases", "taxonomy_management", "bulk_operations", "moderation_publication"],
            "detail": "The B2B Admin internal contract is not registered in the current service",
        },
        {
            "key": "seller_kyc",
            "status": "NOT_CONFIGURED",
            "blocked_actions": ["seller_verification"],
            "detail": "No authoritative seller verification contract is configured",
        },
        {
            "key": "evidence_av_scan",
            "status": "NOT_CONFIGURED",
            "blocked_actions": ["evidence_review"],
            "detail": "No evidence scanning producer or service contract is configured",
        },
        {
            "key": "case_notice_delivery",
            "status": "NOT_CONFIGURED",
            "blocked_actions": ["complaint_request_info", "complaint_warn", "complaint_close", "appeal_decision"],
            "detail": "No recipient-scoped case notice delivery contract is configured",
        },
        {
            "key": "payment_disputes",
            "status": "NOT_CONFIGURED",
            "blocked_actions": ["payment_dispute_review"],
            "detail": "No payment dispute provider contract is configured",
        },
        {
            "key": "delivery_logs",
            "status": "NOT_CONFIGURED",
            "blocked_actions": ["delivery_log_review"],
            "detail": "No delivery log provider contract is configured",
        },
    ]
    as_of = datetime.now(timezone.utc)
    db.add(AuditLog(
        actor_id=current.id,
        action="ADMIN_INTEGRATION_STATUS_READ",
        entity_type="integration_registry",
        entity_id=current.id,
        details={
            "configured_unverified": sum(item["status"] == "CONFIGURED_UNVERIFIED" for item in items),
            "not_configured": sum(item["status"] == "NOT_CONFIGURED" for item in items),
        },
        created_at=as_of,
    ))
    await db.commit()
    return IntegrationStatusResponse(as_of=as_of, items=items)


@router.get(
    "/admin/v1/settings",
    response_model=RuntimeSettingsResponse,
    operation_id="GET_admin_v1_settings",
)
async def get_runtime_settings(
    current: SimpleNamespace = Depends(require_permission("settings.read")),
    db: AsyncSession = Depends(get_db),
) -> RuntimeSettingsResponse:
    """Expose published runtime policies and environment fallbacks without secrets."""
    as_of = datetime.now(timezone.utc)
    queue_values, queue_version = await effective_values(db, "queue_policy")
    workflow_values, workflow_version = await effective_values(db, "workflow_settings")
    can_write_settings = "*" in current.permissions or "settings.write" in current.permissions
    hold_configured = settings.admin_safety_hold_max_seconds is not None
    items = [
        {
            "key": "queue_policy",
            "status": "CONFIGURED_VERSIONED" if queue_version is not None else "CONFIGURED_UNVERSIONED",
            "source": "database" if queue_version is not None else "environment",
            "version": queue_version,
            "writable": can_write_settings,
            "values": queue_values,
            "detail": "Effective values come from the published Admin policy." if queue_version is not None else "Effective values come from service environment configuration; propose a versioned policy to change them.",
        },
        {
            "key": "workflow_settings",
            "status": "CONFIGURED_VERSIONED" if workflow_version is not None else "CONFIGURED_UNVERSIONED",
            "source": "database" if workflow_version is not None else "environment",
            "version": workflow_version,
            "writable": can_write_settings,
            "values": {
                **workflow_values,
            },
            "detail": "Effective values come from the published Admin policy." if workflow_version is not None else "Effective values come from service environment configuration; propose a versioned policy to change them.",
        },
        {
            "key": "deployment_settings",
            "status": "CONFIGURED_UNVERSIONED",
            "source": "environment",
            "version": None,
            "writable": False,
            "values": {"admin_run_outbox_worker": settings.admin_run_outbox_worker},
            "detail": "Worker placement is controlled by deployment configuration.",
        },
        {
            "key": "moderation_sla",
            "status": "CONFIGURED_UNVERSIONED",
            "source": "environment",
            "version": None,
            "writable": False,
            "values": {"moderation_ticket_sla_seconds": settings.moderation_ticket_sla_seconds},
            "detail": "Moderation SLA remains read-only until ADR-ADMIN-13 settles operational thresholds.",
        },
        {
            "key": "safety_hold_policy",
            "status": "CONFIGURED_UNVERSIONED" if hold_configured else "BLOCKED_PENDING_DECISION",
            "source": "environment" if hold_configured else "none",
            "version": None,
            "writable": False,
            "values": {"safety_hold_max_seconds": settings.admin_safety_hold_max_seconds},
            "detail": "Safety-hold duration remains outside versioned runtime settings pending ADR-ADMIN-09.",
        },
        {
            "key": "notification_settings",
            "status": "NOT_CONFIGURED",
            "source": "none",
            "version": None,
            "writable": False,
            "values": {"case_notice_delivery": "NOT_CONFIGURED"},
            "detail": "Recipient-scoped case notice delivery is not configured.",
        },
        {
            "key": "retention_status",
            "status": "BLOCKED_PENDING_DECISION",
            "source": "none",
            "version": None,
            "writable": False,
            "values": {"retention_policy": "NOT_CONFIGURED"},
            "detail": "ADR-ADMIN-10 requires legal approval before retention periods can be configured.",
        },
    ]
    db.add(AuditLog(
        actor_id=current.id,
        action="ADMIN_RUNTIME_SETTINGS_READ",
        entity_type="admin_settings",
        entity_id=current.id,
        details={
            "configured_versioned": int(queue_version is not None) + int(workflow_version is not None),
            "configured_unversioned": int(queue_version is None) + int(workflow_version is None) + 2 + int(hold_configured),
            "not_configured": 1,
            "blocked_pending_decision": int(not hold_configured) + 1,
        },
        created_at=as_of,
    ))
    await db.commit()
    return RuntimeSettingsResponse(as_of=as_of, items=items)


@router.post(
    "/admin/v1/settings/{section}/versions",
    response_model=AdminOperationResponse,
    status_code=202,
    operation_id="POST_admin_v1_settings_section_versions",
)
async def propose_runtime_settings(
    section: RuntimeSection,
    data: RuntimeSettingsProposalInput,
    request: Request,
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    actor: SimpleNamespace = Depends(require_permission("settings.write")),
    db: AsyncSession = Depends(get_db),
) -> AdminOperationResponse:
    try:
        values = validate_values(section, data.values)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "INVALID_RUNTIME_POLICY", "message": str(exc)}) from exc
    code = POLICY_CODES[section]
    rules = {"values": values, "expected_current_version": data.expected_version}
    content_hash = hashlib.sha256(
        json.dumps(rules, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    payload = {
        "code": code,
        "rules": rules,
        "content_hash": content_hash,
        "reason_code": data.reason_code,
        "expected_current_version": data.expected_version,
    }
    request_hash = hashlib.sha256(json.dumps({
        "action": "POLICY_CREATE",
        "section": section,
        "expected_version": data.expected_version,
        "values": values,
        "reason_code": data.reason_code,
    }, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()
    prior = await db.scalar(select(AdminOperation).where(
        AdminOperation.requested_by == actor.id,
        AdminOperation.idempotency_key == str(idempotency_key),
    ))
    if prior is not None:
        if prior.action != "POLICY_CREATE" or not hmac.compare_digest(prior.request_hash, request_hash):
            raise HTTPException(status_code=409, detail={"code": "IDEMPOTENCY_KEY_REUSED", "message": "Idempotency key was used for another settings proposal"})
        return AdminOperationResponse(
            operation_id=prior.id,
            status=prior.status,
            resource_id=prior.entity_id,
            request_id=getattr(request.state, "request_id", None),
            updated_at=prior.updated_at,
            version=prior.version,
        )
    current_version = await active_version(db, section)
    if data.expected_version != current_version:
        raise HTTPException(status_code=412, detail={"code": "RUNTIME_POLICY_VERSION_MISMATCH", "message": "Runtime policy changed; reload the current version before proposing an update"})
    return await _propose(
        db=db,
        request=request,
        actor_id=actor.id,
        key=idempotency_key,
        action="POLICY_CREATE",
        policy_id=uuid4(),
        payload=payload,
        reason_code=data.reason_code,
        request_hash=request_hash,
    )
