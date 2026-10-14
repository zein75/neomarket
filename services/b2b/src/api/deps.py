from uuid import UUID
from secrets import compare_digest

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.config import settings
from src.core.security import decode_access_token
from src.models.seller import Seller
from src.repositories.seller_repo import SellerRepository
from shared.utils.service_auth import verify_service_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


async def verify_service_key(
    x_service_key: str | None = Header(default=None, alias="X-Service-Key"),
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> None:
    if authorization and authorization.lower().startswith("bearer ") and settings.trusted_service_public_keys:
        if verify_service_token(authorization[7:].strip(), trusted_keys=settings.trusted_service_public_keys, audience="neomarket-b2b", allowed_subjects={"b2c", "admin"}):
            return
    if not x_service_key or not compare_digest(x_service_key, settings.service_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "SERVICE_KEY_INVALID",
                "message": "Invalid or missing service key",
            },
        )


async def _seller_from_token(token: str | None, db: AsyncSession) -> Seller:
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    seller_id_str = decode_access_token(token)
    if not seller_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        seller_id = UUID(seller_id_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )
    seller = await SellerRepository(db).get_by_id(seller_id)
    if not seller or not seller.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Seller not found or inactive",
        )
    return seller


async def get_current_seller(
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> Seller:
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
