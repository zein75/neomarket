from datetime import datetime, timezone
from uuid import UUID
from secrets import compare_digest
import hashlib

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.config import settings
from src.core.identity import SellerPrincipal
from src.core.security import decode_access_token_payload
from src.models.seller import Seller
from src.models.seller_session import SellerSession
from src.repositories.seller_repo import SellerRepository
from shared.utils.service_auth import verify_service_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)

SELLER_ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "OWNER": frozenset(
        {"catalog.read", "catalog.write", "inventory.read", "inventory.adjust", "orders.read", "orders.fulfill", "finance.read", "finance.manage", "team.manage"}
    ),
    "MANAGER": frozenset(
        {"catalog.read", "catalog.write", "inventory.read", "inventory.adjust", "orders.read", "orders.fulfill"}
    ),
    "CATALOG_EDITOR": frozenset({"catalog.read", "catalog.write", "inventory.read"}),
    "WAREHOUSE_OPERATOR": frozenset({"catalog.read", "inventory.read", "inventory.adjust", "orders.read", "orders.fulfill"}),
    "SUPPORT": frozenset({"catalog.read", "orders.read"}),
    "FINANCE": frozenset({"catalog.read", "orders.read", "finance.read", "finance.manage"}),
    "VIEWER": frozenset({"catalog.read", "inventory.read", "orders.read", "finance.read"}),
}


def require_seller_permission(permission: str):
    async def check_permission(
        current_seller: Seller | SellerPrincipal = Depends(get_current_seller),
    ) -> Seller | SellerPrincipal:
        role = current_seller.role if isinstance(current_seller, SellerPrincipal) else "OWNER"
        if permission not in SELLER_ROLE_PERMISSIONS.get(role, frozenset()):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "SELLER_PERMISSION_DENIED", "message": "Seller role does not allow this action"},
            )
        return current_seller

    return check_permission


async def verify_service_key(
    x_service_key: str | None = Header(default=None, alias="X-Service-Key"),
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> None:
    if authorization and authorization.lower().startswith("bearer ") and settings.trusted_service_public_keys:
        if verify_service_token(authorization[7:].strip(), trusted_keys=settings.trusted_service_public_keys, audience="neomarket-b2b", allowed_subjects={"b2c", "admin"}):
            return
    if settings.app_env.lower() in {"production", "prod"}:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "SERVICE_TOKEN_REQUIRED", "message": "Signed service token is required"},
        )
    if not x_service_key or not compare_digest(x_service_key, settings.service_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "SERVICE_KEY_INVALID",
                "message": "Invalid or missing service key",
            },
        )


async def _seller_from_token(token: str | None, db: AsyncSession) -> Seller | SellerPrincipal:
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_access_token_payload(token)
    if not payload:
        return await _seller_from_opaque_session(token, db)
    seller_id_str = payload.get("sub")
    session_version = payload.get("session_version")
    if not isinstance(seller_id_str, str) or type(session_version) is not int:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")
    try:
        user_id = UUID(seller_id_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )
    repo = SellerRepository(db)
    organization_claim = payload.get("seller_id")
    if organization_claim is not None:
        if not isinstance(organization_claim, str):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")
        try:
            seller_id = UUID(organization_claim)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")
        organization = await repo.get_by_id(seller_id)
        user = await repo.get_user_by_id(user_id)
        membership = await repo.get_membership(seller_id, user_id)
        if (
            not organization
            or not user
            or not membership
            or not organization.is_active
            or organization.account_status != "ACTIVE"
            or not user.is_active
            or user.email_verified_at is None
            or user.session_version != session_version
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Seller membership is no longer valid",
            )
        return SellerPrincipal(organization, user, membership)

    seller = await repo.get_by_id(user_id)
    if (
        not seller
        or not seller.is_active
        or seller.account_status != "ACTIVE"
        or seller.session_version != session_version
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Seller not found or inactive",
        )
    return seller


async def _seller_from_opaque_session(
    token: str, db: AsyncSession, *, allow_expired: bool = False
) -> SellerPrincipal:
    """Resolve a BFF opaque token without ever accepting it as a JWT."""
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    session = await db.scalar(
        select(SellerSession).where(SellerSession.token_hash == token_hash)
    )
    now = datetime.now(timezone.utc)
    if (
        session is None
        or session.revoked_at is not None
        or (
            session.expires_at <= now
            and (not allow_expired or session.refresh_expires_at <= now)
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    repo = SellerRepository(db)
    organization = await repo.get_by_id(session.seller_id)
    user = await repo.get_user_by_id(session.user_id)
    membership = await repo.get_membership(session.seller_id, session.user_id)
    if (
        organization is None
        or user is None
        or membership is None
        or not organization.is_active
        or organization.account_status != "ACTIVE"
        or not user.is_active
        or user.email_verified_at is None
        or not membership.active
        or user.session_version != session.user_session_version
        or organization.session_version != session.seller_session_version
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Seller session is no longer valid",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return SellerPrincipal(organization, user, membership)


async def get_current_seller(
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> Seller | SellerPrincipal:
    return await _seller_from_token(token, db)


async def get_seller_or_service(
    x_service_key: str | None = Header(default=None, alias="X-Service-Key"),
    authorization: str | None = Header(default=None, alias="Authorization"),
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> Seller | None:
    if authorization and authorization.lower().startswith("bearer ") and settings.trusted_service_public_keys:
        if verify_service_token(authorization[7:].strip(), trusted_keys=settings.trusted_service_public_keys, audience="neomarket-b2b", allowed_subjects={"b2c", "admin"}):
            return None
    if x_service_key is not None:
        if settings.app_env.lower() in {"production", "prod"}:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "SERVICE_TOKEN_REQUIRED", "message": "Signed service token is required"},
            )
        if not compare_digest(x_service_key, settings.service_key):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": "SERVICE_KEY_INVALID",
                    "message": "Invalid or missing service key",
                },
            )
        return None
    return await _seller_from_token(token, db)
