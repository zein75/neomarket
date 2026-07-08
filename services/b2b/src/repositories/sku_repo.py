from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.sku import SKU
from .base import BaseRepository


class SKURepository(BaseRepository[SKU]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, SKU)

    async def list_by_product(self, product_id: UUID) -> list[SKU]:
        result = await self.session.execute(
            select(SKU).where(SKU.product_id == product_id)
        )
        return list(result.scalars().all())
