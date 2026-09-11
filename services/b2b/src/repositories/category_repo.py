from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.category import Category
from src.models.product import Product
from src.models.sku import SKU
from .base import BaseRepository


class CategoryRepository(BaseRepository[Category]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Category)

    async def list_active(self) -> list[Category]:
        result = await self.session.execute(
            select(Category).where(Category.is_active.is_(True))
        )
        return list(result.scalars().all())

    async def get_active(self, category_id: UUID) -> Category | None:
        result = await self.session.execute(
            select(Category).where(
                Category.id == category_id,
                Category.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def count_public_products(self, category_id: UUID) -> int:
        result = await self.session.execute(
            select(func.count(func.distinct(Product.id)))
            .join(SKU, SKU.product_id == Product.id)
            .where(
                Product.category_id == category_id,
                Product.status == "MODERATED",
                Product.deleted.is_(False),
                SKU.stock - SKU.reserved_quantity > 0,
            )
        )
        return int(result.scalar_one())
