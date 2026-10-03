from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.seller import Seller
from .base import BaseRepository


class SellerRepository(BaseRepository[Seller]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Seller)

    async def get_by_email(self, email: str) -> Seller | None:
        result = await self.session.execute(
            select(Seller).where(Seller.email == email)
        )
        return result.scalar_one_or_none()
