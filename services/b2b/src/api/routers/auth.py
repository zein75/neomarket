from datetime import datetime, timezone
import hashlib
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestForm
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import SELLER_ROLE_PERMISSIONS, _seller_from_opaque_session, get_current_seller, get_db, oauth2_scheme, verify_service_key
from src.core.identity import SellerPrincipal
from src.core.redis import get_redis
from src.models.seller import Seller
from src.models.seller_tenant_switch_audit import SellerTenantSwitchAudit
from src.models.seller_session import SellerSession
from src.repositories.seller_repo import SellerRepository
from src.schemas.seller import (
    EmailVerificationRequest,
    EmailVerificationResendRequest,
    SellerCreate,
    SellerRegistrationResponse,
    SellerResponse,
    SellerSuspensionResponse,
    SellerOrganizationResponse,
    SellerPermissionsResponse,
    SellerTenantSwitchRequest,
    TokenResponse,
    SellerSessionResponse,
)
from src.services.auth_service import AuthService
from src.services.email_delivery import (
    require_email_delivery_configured,
    send_verification_email,
)
from src.services.login_rate_limiter import (
    check_login_rate_limit,
    clear_email_login_attempts,
)
from sqlalchemy import select

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=SellerRegistrationResponse,
    status_code=202,
    responses={
        409: {"description": "Email is already registered"},
        429: {"description": "Registration rate limit exceeded"},
        503: {"description": "Email delivery is unavailable"},
    },
)
async def register(
    request: Request,
    data: SellerCreate,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> SellerRegistrationResponse:
    require_email_delivery_configured()
    client_ip = request.client.host if request.client else "unknown"
    await check_login_rate_limit(
        redis, email=str(data.email), client_ip=client_ip, action="register"
    )
    svc = AuthService(db)
    seller, token = await svc.register(data)
    await db.commit()
    await send_verification_email(seller.email, token)
    return SellerRegistrationResponse(
        status="PENDING_EMAIL",
        message="Check your email to verify the address and continue registration.",
    )


@router.post(
    "/verify-email",
    response_model=SellerRegistrationResponse,
    responses={400: {"description": "Verification link is invalid, expired, or used"}},
)
async def verify_email(
    data: EmailVerificationRequest,
    db: AsyncSession = Depends(get_db),
) -> SellerRegistrationResponse:
    state = await AuthService(db).verify_email(data.token)
    await db.commit()
    return SellerRegistrationResponse(
        status=state,
        message="Email confirmed. Your seller account is waiting for review.",
    )


@router.post(
    "/email-verification/resend",
    response_model=SellerRegistrationResponse,
    status_code=202,
    responses={
        429: {"description": "Registration rate limit exceeded"},
        503: {"description": "Email delivery is unavailable"},
    },
)
async def resend_email_verification(
    request: Request,
    data: EmailVerificationResendRequest,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> SellerRegistrationResponse:
    require_email_delivery_configured()
    client_ip = request.client.host if request.client else "unknown"
    email = str(data.email).strip().lower()
    await check_login_rate_limit(redis, email=email, client_ip=client_ip, action="register")
    issued = await AuthService(db).issue_email_verification(email)
    if issued:
        recipient, token = issued
        await db.commit()
        await send_verification_email(recipient, token)
    return SellerRegistrationResponse(
        status="PENDING_EMAIL",
        message="If this account needs verification, a new link has been sent.",
    )


@router.post(
    "/login",
    response_model=TokenResponse,
    responses={
        429: {"description": "Login attempts exceeded; retry after the Retry-After interval"},
        503: {"description": "Login protection service is unavailable"},
    },
)
async def login(
    request: Request,
    form: OAuth2PasswordRequestForm = Depends(),
    seller_id: UUID | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> TokenResponse:
    client_ip = request.client.host if request.client else "unknown"
    await check_login_rate_limit(redis, email=form.username, client_ip=client_ip)
    svc = AuthService(db)
    seller = await svc.authenticate(form.username, form.password, seller_id)
    await clear_email_login_attempts(redis, form.username)
    return svc.create_token(seller)


@router.post(
    "/mfa/challenge",
    status_code=501,
    responses={501: {"description": "Seller MFA provider is not configured"}},
)
async def mfa_challenge(
    current_seller: Seller | SellerPrincipal = Depends(get_current_seller),
) -> None:
    """Keep the high-risk MFA contract explicit until the identity provider is selected."""
    del current_seller
    raise HTTPException(
        status_code=501,
        detail={
            "code": "FEATURE_NOT_CONFIGURED",
            "message": "Seller MFA provider is not configured",
        },
    )


@router.post(
    "/mfa/verify",
    status_code=501,
    responses={501: {"description": "Seller MFA provider is not configured"}},
)
async def mfa_verify(
    current_seller: Seller | SellerPrincipal = Depends(get_current_seller),
) -> None:
    """Fail closed rather than accepting an unverifiable high-risk step-up."""
    del current_seller
    raise HTTPException(
        status_code=501,
        detail={
            "code": "FEATURE_NOT_CONFIGURED",
            "message": "Seller MFA provider is not configured",
        },
    )


@router.post("/session", response_model=TokenResponse)
async def create_session(
    request: Request,
    current_seller: Seller | SellerPrincipal = Depends(get_current_seller),
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Exchange a valid login token for a revocable opaque BFF session."""
    token = await AuthService(db).create_opaque_session(
        current_seller,
        device_label=request.headers.get("X-Device-Label"),
        user_agent=request.headers.get("User-Agent"),
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()
    return token


@router.post("/session/refresh", response_model=TokenResponse)
async def refresh_session(
    request: Request,
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    if not token:
        raise HTTPException(status_code=401, detail="Seller session is required")
    current_seller = await _seller_from_opaque_session(token, db, allow_expired=True)
    session = await db.scalar(
        select(SellerSession).where(
            SellerSession.token_hash == hashlib.sha256(token.encode()).hexdigest(),
            SellerSession.revoked_at.is_(None),
        )
    )
    if session is None or session.refresh_expires_at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Seller session is expired")
    session.revoked_at = datetime.now(timezone.utc)
    rotated = await AuthService(db).create_opaque_session(
        current_seller,
        device_label=request.headers.get("X-Device-Label") or session.device_label,
        user_agent=request.headers.get("User-Agent") or session.user_agent,
        ip_address=request.client.host if request.client else session.ip_address,
        refresh_family_id=session.refresh_family_id,
    )
    await db.commit()
    return rotated


@router.get("/sessions", response_model=list[SellerSessionResponse])
async def list_sessions(
    token: str | None = Depends(oauth2_scheme),
    current_seller: Seller | SellerPrincipal = Depends(get_current_seller),
    db: AsyncSession = Depends(get_db),
) -> list[SellerSessionResponse]:
    user_id = current_seller.user_id if isinstance(current_seller, SellerPrincipal) else current_seller.id
    now = datetime.now(timezone.utc)
    rows = list((await db.scalars(
        select(SellerSession)
        .where(
            SellerSession.user_id == user_id,
            SellerSession.seller_id == current_seller.id,
            SellerSession.revoked_at.is_(None),
            SellerSession.expires_at > now,
        )
        .order_by(SellerSession.created_at.desc(), SellerSession.id.desc())
    )).all())
    current_hash = hashlib.sha256(token.encode()).hexdigest() if token else ""
    return [
        SellerSessionResponse(
            id=row.id,
            seller_id=row.seller_id,
            device_label=row.device_label,
            created_at=row.created_at,
            last_seen_at=row.last_seen_at,
            expires_at=row.expires_at,
            current=row.token_hash == current_hash,
        )
        for row in rows
    ]


@router.post("/logout")
async def logout(
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    """Revoke the current opaque session; JWT clients remain stateless."""
    if token:
        session = await db.scalar(
            select(SellerSession).where(
                SellerSession.token_hash == hashlib.sha256(token.encode()).hexdigest(),
                SellerSession.revoked_at.is_(None),
            )
        )
        if session is not None:
            session.revoked_at = datetime.now(timezone.utc)
            await db.commit()
    return {"ok": True}


@router.get("/me", response_model=SellerResponse)
async def me(current_seller: Seller = Depends(get_current_seller)) -> Seller:
    return current_seller


@router.get("/permissions", response_model=SellerPermissionsResponse)
async def permissions(
    current_seller: Seller | SellerPrincipal = Depends(get_current_seller),
) -> SellerPermissionsResponse:
    role = current_seller.role if isinstance(current_seller, SellerPrincipal) else "OWNER"
    return SellerPermissionsResponse(
        role=role,
        permissions=sorted(SELLER_ROLE_PERMISSIONS.get(role, frozenset())),
    )


@router.get("/organizations", response_model=list[SellerOrganizationResponse])
async def organizations(
    current_seller: Seller = Depends(get_current_seller),
    db: AsyncSession = Depends(get_db),
) -> list[SellerOrganizationResponse]:
    repo = SellerRepository(db)
    if isinstance(current_seller, SellerPrincipal):
        memberships = await repo.list_active_memberships(current_seller.user_id)
        rows: list[SellerOrganizationResponse] = []
        for membership in memberships:
            organization = await repo.get_by_id(membership.seller_id)
            if organization and organization.is_active and organization.account_status == "ACTIVE":
                rows.append(
                    SellerOrganizationResponse(
                        id=organization.id,
                        company_name=organization.company_name,
                        role=membership.role,
                        current=organization.id == current_seller.id,
                    )
                )
        return rows
    return [
        SellerOrganizationResponse(
            id=current_seller.id,
            company_name=current_seller.company_name,
            role="OWNER",
            current=True,
        )
    ]


@router.post("/switch-tenant", response_model=TokenResponse)
async def switch_tenant(
    data: SellerTenantSwitchRequest,
    current_seller: Seller = Depends(get_current_seller),
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    if not isinstance(current_seller, SellerPrincipal):
        raise HTTPException(status_code=409, detail="Tenant switching requires a user membership session")
    repo = SellerRepository(db)
    membership = await repo.get_membership(data.seller_id, current_seller.user_id)
    organization = await repo.get_by_id(data.seller_id)
    if (
        not membership
        or not membership.active
        or not organization
        or not organization.is_active
        or organization.account_status != "ACTIVE"
    ):
        raise HTTPException(status_code=403, detail="No active membership for selected organization")
    if organization.id != current_seller.id:
        db.add(
            SellerTenantSwitchAudit(
                user_id=current_seller.user_id,
                source_seller_id=current_seller.id,
                target_seller_id=organization.id,
                source_role=current_seller.role,
                target_role=membership.role,
            )
        )
        await db.commit()
    target = SellerPrincipal(organization, current_seller.user, membership)
    return AuthService(db).create_token(target)


@router.post("/logout-all")
async def logout_all(
    current_seller: Seller | SellerPrincipal = Depends(get_current_seller),
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    repo = SellerRepository(db)
    if isinstance(current_seller, SellerPrincipal):
        revoked = await repo.revoke_user_sessions(current_seller.user_id)
        if current_seller.user_id == current_seller.id:
            revoked = await repo.revoke_all_sessions(current_seller.id) and revoked
    else:
        revoked = await repo.revoke_all_sessions(current_seller.id)
    if not revoked:
        raise HTTPException(status_code=401, detail="Seller session is no longer valid")
    await db.commit()
    return {"ok": True}


@router.post(
    "/internal/sellers/{seller_id}/suspend",
    response_model=SellerSuspensionResponse,
    responses={401: {"description": "Trusted admin service token required"}, 404: {"description": "Seller not found"}},
)
async def suspend_seller(
    seller_id: UUID,
    _service: None = Depends(verify_service_key),
    db: AsyncSession = Depends(get_db),
) -> SellerSuspensionResponse:
    if not await SellerRepository(db).suspend(seller_id):
        raise HTTPException(status_code=404, detail="Seller not found")
    await db.commit()
    return SellerSuspensionResponse()
