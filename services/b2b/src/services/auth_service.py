from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import create_access_token, hash_password, verify_password
from src.models.seller import Seller
from src.repositories.seller_repo import SellerRepository
from src.schemas.seller import SellerCreate, TokenResponse


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = SellerRepository(session)

    async def register(self, data: SellerCreate) -> Seller:
        existing = await self.repo.get_by_email(data.email)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already registered",
            )
        return await self.repo.create(
            email=data.email,
            hashed_password=hash_password(data.password),
            company_name=data.company_name,
        )

    async def authenticate(self, email: str, password: str) -> Seller:
        seller = await self.repo.get_by_email(email)
        if not seller or not verify_password(password, seller.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password",
            )
        if not seller.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is inactive",
            )
        return seller

    def create_token(self, seller: Seller) -> TokenResponse:
        return TokenResponse(access_token=create_access_token(str(seller.id)))
