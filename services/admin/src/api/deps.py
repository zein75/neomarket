import asyncio
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
from secrets import compare_digest
import jwt
from jwt.exceptions import InvalidTokenError
import httpx
import time
import hashlib
from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.database import get_db
from src.core.config import settings
from src.models.staff_principal import StaffPrincipal, StaffRoleGrant
from src.models.revoked_admin_session import RevokedAdminSession
from src.services.runtime_settings import effective_values
from src.models.admin_web_session import AdminWebSession
from src.models.audit_log import AuditLog
from src.models.moderation import ModerationCard
from src.services.audit_context import bind_actor_context
from shared.utils.service_auth import verify_service_token

_jwks_cache: tuple[float, dict[str, object]] | None = None
_jwks_lock = asyncio.Lock()
_jwks_unknown_kid_refresh_after = 0.0

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "support_viewer": frozenset({"session.read", "session.revoke", "dashboard.read", "moderation.ticket.read", "products.read", "sellers.read", "complaint.read", "appeal.read", "audit.read", "operations.read"}),
    "catalog_moderator": frozenset({"session.read", "session.revoke", "dashboard.read", "moderation.ticket.read", "moderation.ticket.claim", "moderation.decision.write", "products.read", "operations.read"}),
    "senior_moderator": frozenset({"session.read", "session.revoke", "dashboard.read", "moderation.ticket.read", "moderation.ticket.claim", "moderation.decision.write", "moderation.hard_block", "appeal.read", "appeal.decide", "products.read", "products.recheck", "products.safety_hold", "operations.read"}),
    "taxonomy_editor": frozenset({"session.read", "session.revoke", "taxonomy.read", "taxonomy.write", "taxonomy.category.read", "taxonomy.category.write", "taxonomy.attribute.read", "taxonomy.attribute.write", "taxonomy.brand.read", "taxonomy.brand.write", "operations.read"}),
    "taxonomy_approver": frozenset({"session.read", "session.revoke", "taxonomy.read", "taxonomy.approve", "taxonomy.category.read", "taxonomy.category.publish", "taxonomy.attribute.read", "taxonomy.attribute.publish", "taxonomy.brand.read", "taxonomy.brand.publish", "operations.read"}),
    "seller_compliance": frozenset({"session.read", "session.revoke", "sellers.read", "seller.review.read", "sellers.compliance.write", "seller.restrict", "operations.read"}),
    "trust_safety": frozenset({"session.read", "session.revoke", "dashboard.read", "moderation.ticket.read", "moderation.ticket.claim", "moderation.decision.write", "complaint.read", "complaint.read.unassigned", "complaint.evidence.read", "complaint.decide", "appeal.read", "appeal.evidence.read", "appeal.decide", "products.read", "products.recheck", "products.safety_hold", "operations.read"}),
    "operations": frozenset({"session.read", "session.revoke", "operations.read", "operations.write", "operations.cancel", "operations.events.read", "operations.events.retry", "bulk.read", "bulk.write", "bulk.preview", "bulk.propose"}),
    "security_admin": frozenset({"session.read", "session.revoke", "staff.read", "staff.grant", "iam.read", "iam.grant", "iam.revoke", "operations.read", "operations.approve", "operations.cancel", "operations.events.read", "operations.events.retry", "policy.read", "policy.write", "policy.publish", "policy.reason.read", "policy.reason.write", "complaint.read", "complaint.decide", "appeal.read", "appeal.decide", "audit.read", "audit.export", "settings.read", "settings.write"}),
    "auditor": frozenset({"session.read", "session.revoke", "audit.read", "audit.export", "operations.read"}),
}

# Keep super_admin broad, but limited to named permissions that the service
# has registered. A new route must not become accessible through a wildcard.
ROLE_PERMISSIONS["super_admin"] = frozenset().union(
    *ROLE_PERMISSIONS.values(), {"complaint.read.unassigned"}
)

SELLER_SCOPED_PERMISSIONS = frozenset({
    "moderation.ticket.read", "moderation.ticket.claim", "moderation.decision.write", "moderation.hard_block",
    "products.read", "products.recheck", "products.safety_hold", "sellers.read", "seller.review.read", "seller.restrict",
})


async def _record_auth_failure(
    db: AsyncSession,
    request: Request,
    status_code: int,
    *,
    auth_kind: str = "staff",
) -> None:
    """Persist a redacted failed-auth event without retaining credentials or claims."""
    db.add(AuditLog(
        actor_id=None,
        action="ADMIN_AUTH_FAILED",
        entity_type="authentication_attempt",
        entity_id=uuid4(),
        details={
            "auth_kind": auth_kind,
            "method": request.method,
            "path": request.url.path,
            "status_code": status_code,
        },
        created_at=datetime.now(timezone.utc),
    ))
    try:
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise HTTPException(
            status_code=503,
            detail={"code": "AUTH_AUDIT_UNAVAILABLE", "message": "Authentication failure could not be recorded"},
        ) from exc


async def _record_access_denial(
    db: AsyncSession,
    request: Request,
    permission: str,
) -> None:
    """Persist a redacted permission/scope/step-up denial."""
    db.add(AuditLog(
        actor_id=None,
        action="ADMIN_ACCESS_DENIED",
        entity_type="authorization_attempt",
        entity_id=uuid4(),
        details={
            "method": request.method,
            "path": request.url.path,
            "required_permission": permission,
            "status_code": status.HTTP_403_FORBIDDEN,
        },
        created_at=datetime.now(timezone.utc),
    ))
    try:
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise HTTPException(
            status_code=503,
            detail={"code": "ACCESS_AUDIT_UNAVAILABLE", "message": "Access denial could not be recorded"},
        ) from exc


async def _oidc_keys(required_kid: str | None = None) -> dict[str, object]:
    global _jwks_cache, _jwks_unknown_kid_refresh_after
    now = time.monotonic()
    if _jwks_cache and _jwks_cache[0] > now and (required_kid is None or required_kid in _jwks_cache[1]):
        return _jwks_cache[1]
    async with _jwks_lock:
        now = time.monotonic()
        if _jwks_cache and _jwks_cache[0] > now:
            if required_kid is None or required_kid in _jwks_cache[1]:
                return _jwks_cache[1]
            if now < _jwks_unknown_kid_refresh_after:
                return _jwks_cache[1]
            _jwks_unknown_kid_refresh_after = now + 1.0
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(settings.oidc_jwks_url)
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(status_code=503, detail="OIDC provider unavailable") from exc
        raw_keys = payload.get("keys") if isinstance(payload, dict) else None
        if not isinstance(raw_keys, list):
            raise HTTPException(status_code=503, detail="OIDC provider returned an invalid JWKS document")
        keys = {
            item["kid"]: item
            for item in raw_keys
            if isinstance(item, dict) and isinstance(item.get("kid"), str) and item["kid"]
        }
        if not keys:
            raise HTTPException(status_code=503, detail="OIDC provider returned no signing keys")
        refreshed_at = time.monotonic()
        if required_kid is not None and required_kid not in keys:
            _jwks_unknown_kid_refresh_after = refreshed_at + 1.0
        _jwks_cache = (refreshed_at + 300, keys)
        return keys


async def get_current_moderator(
    request: Request,
    x_moderator_id: str | None = Header(default=None, alias="X-Moderator-Id", include_in_schema=False),
    authorization: str | None = Header(default=None, include_in_schema=False),
    db: AsyncSession = Depends(get_db),
) -> SimpleNamespace:
    deployed = not settings.local_dev_auth_enabled
    oidc_auth_paths = {
        "/admin/v1/auth/session": False,
        "/admin/v1/auth/step-up": True,
    }
    requires_step_up_token = request.method == "POST" and oidc_auth_paths.get(request.url.path)
    if deployed and request.method == "POST" and request.url.path in oidc_auth_paths and isinstance(authorization, str) and authorization.lower().startswith("bearer "):
        try:
            principal = await _authenticate_oidc(authorization[7:].strip(), db, require_step_up=bool(requires_step_up_token))
        except HTTPException as exc:
            if exc.status_code in {401, 403}:
                await _record_auth_failure(db, request, exc.status_code)
            raise
        bind_actor_context(principal.id, principal.roles)
        return principal
    access_cookie = request.cookies.get("__Host-nm_admin_access")
    if settings.local_dev_auth_enabled:
        access_cookie = access_cookie or request.cookies.get("nm_admin_access")
    if access_cookie:
        try:
            principal = await _authenticate_web_session(access_cookie, request, db)
        except HTTPException as exc:
            if exc.status_code in {401, 403}:
                await _record_auth_failure(db, request, exc.status_code)
            raise
        bind_actor_context(principal.id, principal.roles)
        return principal
    if not settings.local_dev_auth_enabled:
        await _record_auth_failure(db, request, status.HTTP_401_UNAUTHORIZED)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Opaque Admin session cookie required")
    if not x_moderator_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing moderator identity",
        )
    try:
        moderator_id = UUID(x_moderator_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid moderator identity",
        )
    principal = SimpleNamespace(
        id=moderator_id,
        roles={"development"},
        permissions={"*"},
        oidc_issuer=None,
        oidc_subject=None,
        mfa_verified=False,
        session_token_hash=None,
        session_expires_at=None,
        session_revoked=False,
    )
    bind_actor_context(principal.id, principal.roles)
    return principal


async def _staff_access(
    principal: StaffPrincipal,
    db: AsyncSession,
    now: datetime,
) -> tuple[set[str], set[str], dict[str, set[str]]]:
    grants = await db.scalars(
        select(StaffRoleGrant).where(
            StaffRoleGrant.principal_id == principal.id,
            (StaffRoleGrant.expires_at.is_(None) | (StaffRoleGrant.expires_at > now)),
        )
    )
    active = grants.all()
    roles: set[str] = set()
    permissions: set[str] = set()
    permission_scopes: dict[str, set[str]] = {}
    for grant in active:
        if grant.scope_key == "global":
            scope = "*"
        elif grant.scope_key.startswith("seller:"):
            try:
                scope = f"seller:{UUID(grant.scope_key.removeprefix('seller:'))}"
            except ValueError:
                continue
        else:
            # Unknown scope types do not become effective permissions.
            continue
        if grant.role.startswith("permission:"):
            granted_permissions = {grant.role.removeprefix("permission:")}
        else:
            roles.add(grant.role)
            granted_permissions = set(ROLE_PERMISSIONS.get(grant.role, frozenset()))
        for granted_permission in granted_permissions:
            if scope != "*" and granted_permission not in SELLER_SCOPED_PERMISSIONS:
                continue
            permissions.add(granted_permission)
            permission_scopes.setdefault(granted_permission, set()).add(scope)
    if not permissions:
        raise HTTPException(status_code=403, detail="No active Admin permissions")
    return roles, permissions, permission_scopes


async def staff_has_permission(
    principal: StaffPrincipal,
    permission: str,
    db: AsyncSession,
    now: datetime | None = None,
) -> bool:
    if principal.status != "ACTIVE":
        return False
    try:
        _, permissions, _ = await _staff_access(principal, db, now or datetime.now(timezone.utc))
    except HTTPException as exc:
        if exc.status_code == 403:
            return False
        raise
    return permission in permissions


async def _authenticate_oidc(token: str, db: AsyncSession, *, require_step_up: bool = False) -> SimpleNamespace:
    if not settings.oidc_issuer or not settings.oidc_jwks_url:
        raise HTTPException(status_code=503, detail="OIDC is not configured")
    try:
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        if not isinstance(kid, str) or not kid:
            raise InvalidTokenError("Missing OIDC key id")
        key = (await _oidc_keys(required_kid=kid)).get(kid)
        if not key:
            raise InvalidTokenError("Unknown OIDC key id")
        payload = jwt.decode(
            token,
            key,
            algorithms=["RS256", "RS384", "RS512"],
            issuer=settings.oidc_issuer,
            audience=settings.oidc_audience,
            options={"require": ["sub", "iat", "nbf", "exp"]},
        )
        amr = payload.get("amr", [])
        acr = payload.get("acr")
        mfa_checks = []
        if settings.oidc_required_amr.strip():
            mfa_checks.append(isinstance(amr, list) and settings.oidc_required_amr.strip() in amr)
        if settings.oidc_required_acr.strip():
            mfa_checks.append(isinstance(acr, str) and acr == settings.oidc_required_acr.strip())
        if not mfa_checks or not all(mfa_checks):
            raise HTTPException(status_code=403, detail="MFA claim required")
        if require_step_up:
            workflow_settings, _ = await effective_values(db, "workflow_settings")
            step_up_max_age_seconds = int(workflow_settings["admin_step_up_max_age_seconds"])
            step_up_checks = []
            if settings.oidc_step_up_required_amr.strip():
                step_up_checks.append(
                    isinstance(amr, list) and settings.oidc_step_up_required_amr.strip() in amr
                )
            if settings.oidc_step_up_required_acr.strip():
                step_up_checks.append(
                    isinstance(acr, str) and acr == settings.oidc_step_up_required_acr.strip()
                )
            try:
                auth_time = datetime.fromtimestamp(int(payload["auth_time"]), timezone.utc)
            except (KeyError, ValueError, TypeError, OverflowError, OSError) as exc:
                raise HTTPException(status_code=403, detail="Recent step-up authentication required") from exc
            now = datetime.now(timezone.utc)
            age_seconds = (now - auth_time).total_seconds()
            if (
                not step_up_checks
                or not all(step_up_checks)
                or age_seconds < -60
                or age_seconds > step_up_max_age_seconds
            ):
                raise HTTPException(status_code=403, detail="Recent step-up authentication required")
        else:
            raw_auth_time = payload.get("auth_time")
            try:
                auth_time = datetime.fromtimestamp(int(raw_auth_time), timezone.utc) if raw_auth_time is not None else None
            except (ValueError, TypeError, OverflowError, OSError):
                auth_time = None
        subject = payload.get("sub")
        if not isinstance(subject, str) or not subject.strip():
            raise HTTPException(status_code=401, detail="Invalid OIDC subject")
        jti = payload.get("jti")
        if not isinstance(jti, str) or not jti.strip() or len(jti) > 1024:
            raise HTTPException(status_code=401, detail="OIDC token ID is required")
        principal = await db.scalar(select(StaffPrincipal).where(
            StaffPrincipal.oidc_issuer == settings.oidc_issuer,
            StaffPrincipal.oidc_subject == subject,
        ))
        if principal is None or principal.status != "ACTIVE":
            raise HTTPException(status_code=403, detail="Staff principal is not provisioned or is inactive")
        now = datetime.now(timezone.utc)
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        jti_hash = hashlib.sha256(f"{settings.oidc_issuer}\0{subject}\0{jti}".encode("utf-8")).hexdigest()
        revoked_token = await db.scalar(select(RevokedAdminSession.id).where(
            RevokedAdminSession.token_hash == token_hash,
            RevokedAdminSession.expires_at > now,
        ))
        issued_at = datetime.fromtimestamp(int(payload["iat"]), timezone.utc)
        if revoked_token is not None or (principal.sessions_revoked_at is not None and issued_at <= principal.sessions_revoked_at):
            raise HTTPException(status_code=401, detail="OIDC session has been revoked")
        roles, permissions, permission_scopes = await _staff_access(principal, db, now)
        return SimpleNamespace(
            id=principal.id, roles=roles, permissions=permissions, permission_scopes=permission_scopes,
            oidc_issuer=principal.oidc_issuer, oidc_subject=principal.oidc_subject,
            mfa_verified=True, session_token_hash=token_hash,
            session_expires_at=datetime.fromtimestamp(int(payload["exp"]), timezone.utc),
            oidc_jti_hash=jti_hash, oidc_acr=acr if isinstance(acr, str) else None,
            oidc_auth_time=auth_time,
            session_revoked=False, source="oidc",
        )
    except HTTPException:
        raise
    except (InvalidTokenError, ValueError, TypeError, OverflowError, OSError) as exc:
        raise HTTPException(status_code=401, detail="Invalid OIDC bearer token") from exc


async def _authenticate_web_session(token: str, request: Request, db: AsyncSession) -> SimpleNamespace:
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    session = await db.scalar(select(AdminWebSession).where(AdminWebSession.token_hash == token_hash))
    now = datetime.now(timezone.utc)
    if session is None or session.idle_expires_at <= now or session.absolute_expires_at <= now:
        raise HTTPException(status_code=401, detail="Admin web session is invalid or expired")
    session_revoked = session.revoked_at is not None
    logout_replay = request.method.upper() == "POST" and request.url.path == "/admin/v1/session/logout"
    if session_revoked and not logout_replay:
        raise HTTPException(status_code=401, detail="Admin web session has been revoked")
    principal = await db.get(StaffPrincipal, session.principal_id)
    if principal is None or principal.status != "ACTIVE":
        raise HTTPException(status_code=401, detail="Admin principal is inactive")
    if principal.sessions_revoked_at is not None and session.created_at <= principal.sessions_revoked_at and not logout_replay:
        raise HTTPException(status_code=401, detail="Admin web session has been revoked")
    if request.method.upper() not in {"GET", "HEAD", "OPTIONS"}:
        csrf_cookie = request.cookies.get("__Host-nm_admin_csrf")
        if settings.local_dev_auth_enabled:
            csrf_cookie = csrf_cookie or request.cookies.get("nm_admin_csrf")
        csrf_header = request.headers.get("X-CSRF-Token")
        origin = request.headers.get("Origin")
        if (
            not csrf_cookie or not csrf_header or not compare_digest(csrf_cookie, csrf_header)
            or not compare_digest(hashlib.sha256(csrf_header.encode()).hexdigest(), session.csrf_hash)
            or not settings.admin_public_origin or origin != settings.admin_public_origin.rstrip("/")
            or request.headers.get("Sec-Fetch-Site", "").lower() == "cross-site"
        ):
            raise HTTPException(status_code=403, detail={"code": "CSRF_VALIDATION_FAILED", "message": "Admin session CSRF validation failed"})
    if not session_revoked and (now - session.last_seen_at).total_seconds() >= 60:
        workflow_settings, _ = await effective_values(db, "workflow_settings")
        session.last_seen_at = now
        session.idle_expires_at = min(
            now + timedelta(seconds=int(workflow_settings["admin_session_idle_ttl_seconds"])),
            session.absolute_expires_at,
        )
        await db.commit()
    roles, permissions, permission_scopes = await _staff_access(principal, db, now)
    return SimpleNamespace(
        id=principal.id, roles=roles, permissions=permissions, permission_scopes=permission_scopes,
        oidc_issuer=principal.oidc_issuer, oidc_subject=principal.oidc_subject,
        mfa_verified=True, session_token_hash=token_hash,
        session_expires_at=session.absolute_expires_at,
        web_session_id=session.id, csrf_hash=session.csrf_hash, source="cookie", session_revoked=session_revoked,
        step_up_expires_at=session.step_up_expires_at,
    )


def require_recent_step_up(principal: SimpleNamespace) -> None:
    deployed = not settings.local_dev_auth_enabled
    expires_at = getattr(principal, "step_up_expires_at", None)
    if deployed and (not isinstance(expires_at, datetime) or expires_at <= datetime.now(timezone.utc)):
        raise HTTPException(
            status_code=403,
            detail={"code": "STEP_UP_REQUIRED", "message": "Recent step-up authentication is required for this action"},
        )


async def authorize_permission_scope(
    permission: str,
    request: Request,
    principal: SimpleNamespace,
    db: AsyncSession,
) -> None:
    if "*" in getattr(principal, "permissions", set()):
        return
    scopes = getattr(principal, "permission_scopes", {}).get(permission, set())
    if "*" in scopes:
        return
    seller_scopes: set[UUID] = set()
    for scope in scopes:
        if scope.startswith("seller:"):
            try:
                seller_scopes.add(UUID(scope.removeprefix("seller:")))
            except ValueError:
                continue
    if not seller_scopes:
        raise HTTPException(status_code=403, detail={"code": "SCOPE_DENIED", "message": "No applicable Admin resource scope is granted"})

    candidate_seller_ids: set[UUID] = set()
    raw_seller_id = request.path_params.get("seller_id") or request.query_params.get("seller_id")
    if raw_seller_id is not None:
        try:
            candidate_seller_ids.add(UUID(str(raw_seller_id)))
        except ValueError as exc:
            raise HTTPException(status_code=403, detail={"code": "SCOPE_DENIED", "message": "Admin resource scope cannot be verified for this request"}) from exc
    if not candidate_seller_ids and request.path_params.get("ticket_id") is not None:
        try:
            ticket_id = UUID(str(request.path_params["ticket_id"]))
        except ValueError as exc:
            raise HTTPException(status_code=403, detail={"code": "SCOPE_DENIED", "message": "Admin resource scope cannot be verified for this request"}) from exc
        raw_seller_id = await db.scalar(select(ModerationCard.seller_id).where(ModerationCard.id == ticket_id))
        if raw_seller_id is not None:
            candidate_seller_ids.add(raw_seller_id)
    if not candidate_seller_ids and request.path_params.get("product_id") is not None:
        try:
            product_id = UUID(str(request.path_params["product_id"]))
        except ValueError as exc:
            raise HTTPException(status_code=403, detail={"code": "SCOPE_DENIED", "message": "Admin resource scope cannot be verified for this request"}) from exc
        candidate_seller_ids.update((await db.scalars(
            select(ModerationCard.seller_id).where(
                ModerationCard.product_id == product_id,
                ModerationCard.seller_id.is_not(None),
            ).distinct()
        )).all())
    if not candidate_seller_ids:
        # The queue handler applies the full set of seller scopes in its query.
        if request.method == "GET" and request.url.path == "/admin/v1/moderation/tickets" and not request.query_params.get("seller_id"):
            return
        raise HTTPException(status_code=403, detail={"code": "SCOPE_DENIED", "message": "Admin resource scope cannot be verified for this request"})
    if not candidate_seller_ids.issubset(seller_scopes):
        raise HTTPException(status_code=403, detail={"code": "SCOPE_DENIED", "message": "Admin resource is outside the granted seller scope"})


def require_permission(permission: str):
    async def dependency(
        request: Request,
        principal: SimpleNamespace = Depends(get_current_moderator),
        db: AsyncSession = Depends(get_db),
    ) -> SimpleNamespace:
        try:
            if "*" not in getattr(principal, "permissions", set()) and permission not in getattr(principal, "permissions", set()):
                raise HTTPException(status_code=403, detail={"code": "PERMISSION_DENIED", "message": "Required Admin permission is missing"})
            if "*" not in getattr(principal, "permissions", set()):
                await authorize_permission_scope(permission, request, principal, db)
            high_risk_permissions = {
                "audit.export", "staff.grant", "iam.grant", "iam.revoke", "operations.approve", "operations.events.retry", "appeal.decide", "policy.write", "policy.publish", "settings.write",
                "taxonomy.category.publish", "taxonomy.attribute.publish", "taxonomy.brand.publish",
                "bulk.preview", "bulk.propose", "products.safety_hold", "seller.restrict",
            }
            if (
                permission in high_risk_permissions
                or request.url.path.endswith("/move")
                or (permission == "complaint.read" and "complaint.read.unassigned" in principal.permissions)
            ):
                require_recent_step_up(principal)
        except HTTPException as exc:
            if exc.status_code == status.HTTP_403_FORBIDDEN:
                await _record_access_denial(db, request, permission)
            raise
        return principal

    dependency.required_permission = permission
    return dependency


async def verify_service_key(
    request: Request,
    x_service_key: str | None = Header(default=None, alias="X-Service-Key"),
    authorization: str | None = Header(default=None, alias="Authorization"),
    db: AsyncSession = Depends(get_db),
) -> None:
    if authorization and authorization.lower().startswith("bearer ") and settings.trusted_service_public_keys:
        if verify_service_token(authorization[7:].strip(), trusted_keys=settings.trusted_service_public_keys, audience="neomarket-admin", allowed_subjects={"b2b", "b2c"}):
            return
    if not settings.local_dev_auth_enabled:
        await _record_auth_failure(db, request, status.HTTP_401_UNAUTHORIZED, auth_kind="service")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "SERVICE_TOKEN_REQUIRED", "message": "Signed service token is required"},
        )
    if not x_service_key or not compare_digest(x_service_key, settings.service_key):
        await _record_auth_failure(db, request, status.HTTP_401_UNAUTHORIZED, auth_kind="service")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "message": "Invalid service key"},
        )
