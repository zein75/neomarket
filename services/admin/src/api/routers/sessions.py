import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_moderator, require_permission
from src.api.router import AdminAPIRoute
from src.core.config import settings
from src.core.database import get_db
from src.models.admin_operation import AdminOperation
from src.models.audit_log import AuditLog
from src.models.revoked_admin_session import RevokedAdminSession
from src.models.admin_web_session import AdminWebSession
from src.models.admin_oidc_token_receipt import AdminOidcTokenReceipt
from src.models.staff_principal import StaffPrincipal
from src.schemas.admin import AdminOperationResponse, ReasonAction
from src.services.runtime_settings import effective_values

router = APIRouter(route_class=AdminAPIRoute, tags=["session", "staff"])


class SessionPrincipal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str
    staff_id: UUID
    roles: list[str]
    permissions: list[str]
    scopes: dict[str, list[str]]


class SessionStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    authenticated: bool
    principal: SessionPrincipal
    csrf_token: str


class SessionCreated(BaseModel):
    model_config = ConfigDict(extra="forbid")

    authenticated: bool
    csrf_token: str
    expires_at: datetime


class StaffSessionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    created_at: datetime
    last_seen_at: datetime
    idle_expires_at: datetime
    absolute_expires_at: datetime
    step_up_expires_at: datetime | None = None
    revoked_at: datetime | None = None
    current: bool
    mfa_verified: bool
    device: str | None = None


class StaffSessionPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[StaffSessionItem]


def _cookie_names() -> tuple[str, str, bool]:
    if not settings.local_dev_auth_enabled:
        return "__Host-nm_admin_access", "__Host-nm_admin_csrf", True
    return "nm_admin_access", "nm_admin_csrf", False


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"


def _clear_session_cookies(response: Response) -> None:
    access_name, csrf_name, secure = _cookie_names()
    for name, http_only in ((access_name, True), (csrf_name, False)):
        response.set_cookie(
            name, "", max_age=0, expires=0, path="/", secure=secure,
            httponly=http_only, samesite="lax" if http_only else "strict",
        )
    if secure:
        for name, http_only in (("nm_admin_access", True), ("nm_admin_csrf", False)):
            response.set_cookie(name, "", max_age=0, expires=0, path="/", secure=False,
                                httponly=http_only, samesite="lax" if http_only else "strict")


@router.post("/admin/v1/auth/session", response_model=SessionCreated, status_code=201)
async def create_web_session(
    request: Request,
    response: Response,
    current: SimpleNamespace = Depends(get_current_moderator),
    db: AsyncSession = Depends(get_db),
) -> SessionCreated:
    origin = request.headers.get("Origin")
    if not settings.admin_public_origin or origin != settings.admin_public_origin.rstrip("/"):
        raise HTTPException(status_code=403, detail={"code": "UNTRUSTED_ORIGIN", "message": "Admin session exchange origin is not trusted"})
    if getattr(current, "source", None) != "oidc" or not current.mfa_verified:
        raise HTTPException(status_code=401, detail={"code": "OIDC_EXCHANGE_REQUIRED", "message": "A verified OIDC/MFA bearer token is required for session exchange"})
    now = datetime.now(timezone.utc)
    workflow_settings, _ = await effective_values(db, "workflow_settings")
    absolute_expires_at = min(
        now + timedelta(seconds=int(workflow_settings["admin_session_absolute_ttl_seconds"])),
        current.session_expires_at,
    )
    if absolute_expires_at <= now + timedelta(minutes=1):
        raise HTTPException(status_code=401, detail={"code": "OIDC_SESSION_TOO_SHORT", "message": "OIDC session expires too soon to create an Admin session"})
    idle_expires_at = min(
        now + timedelta(seconds=int(workflow_settings["admin_session_idle_ttl_seconds"])),
        absolute_expires_at,
    )
    token = secrets.token_urlsafe(48)
    csrf_token = secrets.token_urlsafe(32)
    session = AdminWebSession(
        id=uuid4(),
        principal_id=current.id,
        token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
        user_agent="".join(ch for ch in request.headers.get("User-Agent", "") if ch.isprintable())[:512] or None,
        oidc_jti_hash=current.oidc_jti_hash,
        oidc_token_expires_at=current.session_expires_at,
        csrf_hash=hashlib.sha256(csrf_token.encode("utf-8")).hexdigest(),
        created_at=now,
        last_seen_at=now,
        idle_expires_at=idle_expires_at,
        absolute_expires_at=absolute_expires_at,
    )
    db.add(session)
    db.add(AdminOidcTokenReceipt(
        jti_hash=current.oidc_jti_hash,
        principal_id=current.id,
        purpose="SESSION_EXCHANGE",
        expires_at=current.session_expires_at,
    ))
    db.add(AuditLog(
        actor_id=current.id, action="ADMIN_WEB_SESSION_CREATED", entity_type="staff", entity_id=current.id,
        details={"session_id": str(session.id), "expires_at": absolute_expires_at.isoformat(), "mfa_verified": True},
        created_at=now,
    ))
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        original = getattr(exc, "orig", None)
        diagnostic = getattr(original, "diag", None)
        constraint_name = getattr(diagnostic, "constraint_name", None)
        if constraint_name in {"uq_admin_web_sessions_oidc_jti_hash", "uq_admin_oidc_token_receipts_jti_hash"}:
            raise HTTPException(status_code=409, detail={"code": "OIDC_TOKEN_REPLAYED", "message": "This OIDC token has already been exchanged for an Admin session"}) from exc
        raise
    access_name, csrf_name, secure = _cookie_names()
    max_age = max(0, int((absolute_expires_at - now).total_seconds()))
    response.set_cookie(access_name, token, max_age=max_age, path="/", secure=secure, httponly=True, samesite="lax")
    response.set_cookie(csrf_name, csrf_token, max_age=max_age, path="/", secure=secure, httponly=False, samesite="strict")
    _no_store(response)
    return SessionCreated(authenticated=True, csrf_token=csrf_token, expires_at=absolute_expires_at)


@router.post(
    "/admin/v1/auth/step-up",
    status_code=204,
    operation_id="POST_admin_v1_auth_step_up",
    responses={401: {"description": "Authentication required"}, 403: {"description": "Recent step-up authentication required"}, 409: {"description": "OIDC token replay"}},
)
async def step_up_session(
    request: Request,
    response: Response,
    current: SimpleNamespace = Depends(get_current_moderator),
    db: AsyncSession = Depends(get_db),
) -> Response:
    origin = request.headers.get("Origin")
    if not settings.admin_public_origin or origin != settings.admin_public_origin.rstrip("/"):
        raise HTTPException(status_code=403, detail={"code": "UNTRUSTED_ORIGIN", "message": "Admin step-up origin is not trusted"})
    if getattr(current, "source", None) != "oidc" or not current.mfa_verified:
        raise HTTPException(status_code=401, detail={"code": "OIDC_STEP_UP_REQUIRED", "message": "A freshly authenticated OIDC bearer token is required"})
    access_name, csrf_name, _ = _cookie_names()
    access_token = request.cookies.get(access_name, "")
    csrf_cookie = request.cookies.get(csrf_name, "")
    csrf_header = request.headers.get("X-CSRF-Token", "")
    if (
        not access_token or not csrf_cookie or not csrf_header
        or not hmac.compare_digest(csrf_cookie, csrf_header)
        or request.headers.get("Sec-Fetch-Site", "").lower() == "cross-site"
    ):
        raise HTTPException(status_code=403, detail={"code": "CSRF_VALIDATION_FAILED", "message": "Admin step-up CSRF validation failed"})
    session_hash = hashlib.sha256(access_token.encode("utf-8")).hexdigest()
    session = await db.scalar(select(AdminWebSession).where(
        AdminWebSession.token_hash == session_hash,
        AdminWebSession.principal_id == current.id,
    ).with_for_update())
    now = datetime.now(timezone.utc)
    if (
        session is None or session.revoked_at is not None
        or session.idle_expires_at <= now or session.absolute_expires_at <= now
        or not hmac.compare_digest(hashlib.sha256(csrf_header.encode("utf-8")).hexdigest(), session.csrf_hash)
    ):
        raise HTTPException(status_code=401, detail={"code": "ADMIN_SESSION_INVALID", "message": "An active Admin session is required for step-up"})
    auth_time = getattr(current, "oidc_auth_time", None)
    if not isinstance(auth_time, datetime):
        raise HTTPException(status_code=403, detail={"code": "STEP_UP_REQUIRED", "message": "The IdP token must include a recent auth_time"})
    workflow_settings, _ = await effective_values(db, "workflow_settings")
    session.step_up_expires_at = min(
        auth_time + timedelta(seconds=int(workflow_settings["admin_step_up_max_age_seconds"])),
        session.absolute_expires_at,
    )
    db.add(AdminOidcTokenReceipt(
        jti_hash=current.oidc_jti_hash,
        principal_id=current.id,
        purpose="STEP_UP",
        expires_at=current.session_expires_at,
    ))
    db.add(AuditLog(
        actor_id=current.id,
        action="ADMIN_STEP_UP_AUTHENTICATED",
        entity_type="admin_web_session",
        entity_id=session.id,
        details={"step_up_expires_at": session.step_up_expires_at.isoformat(), "acr": current.oidc_acr},
        created_at=now,
    ))
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        original = getattr(exc, "orig", None)
        diagnostic = getattr(original, "diag", None)
        if getattr(diagnostic, "constraint_name", None) == "uq_admin_oidc_token_receipts_jti_hash":
            raise HTTPException(status_code=409, detail={"code": "OIDC_TOKEN_REPLAYED", "message": "This OIDC token has already been used"}) from exc
        raise
    _no_store(response)
    response.status_code = 204
    return response


@router.get("/session", response_model=SessionStatus, include_in_schema=False)
async def read_web_session(
    request: Request,
    response: Response,
    current: SimpleNamespace = Depends(require_permission("session.read")),
) -> SessionStatus:
    csrf_name = _cookie_names()[1]
    csrf_token = request.cookies.get(csrf_name, "")
    csrf_hash = getattr(current, "csrf_hash", None)
    if not csrf_token or not csrf_hash or not hmac.compare_digest(hashlib.sha256(csrf_token.encode("utf-8")).hexdigest(), csrf_hash):
        raise HTTPException(status_code=401, detail={"code": "ADMIN_SESSION_INVALID", "message": "Admin session CSRF binding is unavailable"})
    _no_store(response)
    return SessionStatus(
        authenticated=True,
        principal=SessionPrincipal(
            role="admin",
            staff_id=current.id,
            roles=sorted(current.roles),
            permissions=sorted(current.permissions),
            scopes={permission: sorted(scopes) for permission, scopes in getattr(current, "permission_scopes", {}).items()},
        ),
        csrf_token=csrf_token,
    )


@router.get(
    "/admin/v1/staff/{staff_id}/sessions",
    response_model=StaffSessionPage,
    response_model_exclude_none=True,
    operation_id="GET_admin_v1_staff_staff_id_sessions",
)
async def list_staff_sessions(
    staff_id: UUID,
    response: Response,
    limit: int = Query(default=50, ge=1, le=100),
    current: SimpleNamespace = Depends(require_permission("staff.read")),
    db: AsyncSession = Depends(get_db),
) -> StaffSessionPage:
    staff = await db.get(StaffPrincipal, staff_id)
    if staff is None:
        raise HTTPException(status_code=404, detail={"code": "STAFF_NOT_FOUND", "message": "Staff principal not found"})
    sessions = (await db.scalars(
        select(AdminWebSession)
        .where(AdminWebSession.principal_id == staff_id)
        .order_by(AdminWebSession.created_at.desc(), AdminWebSession.id.desc())
        .limit(limit)
    )).all()
    db.add(AuditLog(
        actor_id=current.id,
        action="STAFF_SESSIONS_VIEWED",
        entity_type="staff",
        entity_id=staff_id,
        details={"count": len(sessions)},
        created_at=datetime.now(timezone.utc),
    ))
    await db.commit()
    _no_store(response)
    return StaffSessionPage(items=[
        StaffSessionItem(
            session_id=session.id,
            created_at=session.created_at,
            last_seen_at=session.last_seen_at,
            idle_expires_at=session.idle_expires_at,
            absolute_expires_at=session.absolute_expires_at,
            step_up_expires_at=session.step_up_expires_at,
            revoked_at=(
                session.revoked_at
                or (
                    staff.sessions_revoked_at
                    if staff.sessions_revoked_at is not None and session.created_at <= staff.sessions_revoked_at
                    else None
                )
            ),
            current=session.id == getattr(current, "web_session_id", None),
            mfa_verified=True,
            device=session.user_agent,
        )
        for session in sessions
    ])


def _operation(operation: AdminOperation, request: Request) -> AdminOperationResponse:
    return AdminOperationResponse(
        operation_id=operation.id, status=operation.status, resource_id=operation.entity_id,
        request_id=getattr(request.state, "request_id", None), updated_at=operation.updated_at, version=operation.version,
    )


@router.post("/admin/v1/session/logout", response_model=AdminOperationResponse, status_code=202)
async def logout_session(
    request: Request,
    response: Response,
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    current: SimpleNamespace = Depends(require_permission("session.revoke")),
    db: AsyncSession = Depends(get_db),
) -> AdminOperationResponse:
    token_hash = getattr(current, "session_token_hash", None)
    expires_at = getattr(current, "session_expires_at", None)
    web_session_id = getattr(current, "web_session_id", None)
    if not token_hash or not isinstance(expires_at, datetime) or web_session_id is None:
        raise HTTPException(status_code=503, detail={"code": "SESSION_REVOCATION_UNAVAILABLE", "message": "A configured Admin web session is required"})
    request_hash = hashlib.sha256(json.dumps({"action": "SESSION_LOGOUT", "token_hash": token_hash}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    previous = await db.scalar(select(AdminOperation).where(
        AdminOperation.requested_by == current.id, AdminOperation.idempotency_key == str(idempotency_key)))
    if previous is not None:
        if previous.action != "SESSION_LOGOUT" or not hmac.compare_digest(previous.request_hash, request_hash):
            raise HTTPException(status_code=409, detail={"code": "IDEMPOTENCY_KEY_REUSED", "message": "Idempotency key was used for another operation"})
        _clear_session_cookies(response)
        _no_store(response)
        return _operation(previous, request)
    if getattr(current, "session_revoked", False):
        raise HTTPException(status_code=401, detail={"code": "SESSION_REVOKED", "message": "Admin session has been revoked"})
    now = datetime.now(timezone.utc)
    web_session = await db.scalar(select(AdminWebSession).where(AdminWebSession.id == web_session_id).with_for_update())
    if web_session is None or web_session.revoked_at is not None:
        raise HTTPException(status_code=401, detail={"code": "SESSION_REVOKED", "message": "Admin session has already been revoked"})
    web_session.revoked_at = now
    operation = AdminOperation(
        action="SESSION_LOGOUT", entity_type="staff", entity_id=current.id,
        payload={"revoked_token_hash": token_hash}, status="APPLIED", version=1,
        idempotency_key=str(idempotency_key), request_hash=request_hash, requested_by=current.id,
        reason_code="SESSION_LOGOUT", updated_at=now,
    )
    db.add(operation)
    db.add(RevokedAdminSession(principal_id=current.id, token_hash=token_hash, expires_at=expires_at))
    db.add(AuditLog(actor_id=current.id, action="SESSION_LOGOUT", entity_type="staff", entity_id=current.id,
        details={"operation_id": str(operation.id)}, created_at=now))
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail={"code": "SESSION_ALREADY_REVOKED", "message": "Admin session has already been revoked"}) from exc
    _clear_session_cookies(response)
    _no_store(response)
    return _operation(operation, request)


@router.post("/admin/v1/staff/{staff_id}/revoke-sessions", response_model=AdminOperationResponse, status_code=202)
async def propose_session_revocation(
    staff_id: UUID,
    data: ReasonAction,
    request: Request,
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    current: SimpleNamespace = Depends(require_permission("iam.revoke")),
    db: AsyncSession = Depends(get_db),
) -> AdminOperationResponse:
    payload = {"reason_code": data.reason_code, "comment": data.comment}
    request_hash = hashlib.sha256(json.dumps({"staff_id": str(staff_id), "payload": payload}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    previous = await db.scalar(select(AdminOperation).where(
        AdminOperation.requested_by == current.id, AdminOperation.idempotency_key == str(idempotency_key)))
    if previous is not None:
        if previous.action != "STAFF_SESSION_REVOKE" or previous.entity_id != staff_id or not hmac.compare_digest(previous.request_hash, request_hash):
            raise HTTPException(status_code=409, detail={"code": "IDEMPOTENCY_KEY_REUSED", "message": "Idempotency key was used for another operation"})
        return _operation(previous, request)
    staff = await db.scalar(select(StaffPrincipal).where(StaffPrincipal.id == staff_id).with_for_update())
    if staff is None:
        raise HTTPException(status_code=404, detail={"code": "STAFF_NOT_FOUND", "message": "Staff principal not found"})
    now = datetime.now(timezone.utc)
    operation = AdminOperation(
        action="STAFF_SESSION_REVOKE", entity_type="staff", entity_id=staff_id,
        payload={**payload, "expected_staff_version": staff.version}, status="WAITING_APPROVAL", version=1,
        idempotency_key=str(idempotency_key), request_hash=request_hash, requested_by=current.id,
        reason_code=data.reason_code, updated_at=now,
    )
    db.add(operation)
    db.add(AuditLog(actor_id=current.id, action="STAFF_SESSION_REVOKE_PROPOSED", entity_type="staff", entity_id=staff_id,
        details={"operation_id": str(operation.id), "reason_code": data.reason_code}, created_at=now))
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail={"code": "SESSION_REVOCATION_CONFLICT", "message": "Session revocation request conflicts with another operation"}) from exc
    return _operation(operation, request)
