from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.security import decode_access_token
from src.models.seller import Seller
from src.repositories.seller_repo import SellerRepository

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


async def get_current_seller(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> Seller:
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
