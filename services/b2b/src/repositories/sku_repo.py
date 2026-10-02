from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

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

    async def get_with_product(self, sku_id: UUID) -> SKU | None:
        result = await self.session.execute(
            select(SKU)
            .where(SKU.id == sku_id)
            .options(selectinload(SKU.product))
        )
        return result.scalar_one_or_none()

    async def list_for_update(self, sku_ids: list[UUID]) -> list[SKU]:
        result = await self.session.execute(
            select(SKU)
            .where(SKU.id.in_(sku_ids))
            # PostgreSQL rejects FOR UPDATE over joinedload's nullable outer
            # join. Lock SKU rows only; fetch the parent in a separate query.
            .options(selectinload(SKU.product))
            # Acquire overlapping SKU locks in one stable order so two carts
            # containing the same SKUs in a different order cannot deadlock.
            .order_by(SKU.id)
            .with_for_update()
        )
        return list(result.scalars().all())

    async def create_sku(
        self,
        *,
        product_id: UUID,
        name: str,
        price: int,
        stock: int,
        images: list[str],
    ) -> SKU:
        sku = SKU(
            product_id=product_id,
            name=name,
            price=price,
            stock=stock,
            images=images,
        )
        self.session.add(sku)
        await self.session.flush()
        await self.session.refresh(sku)
        return sku
