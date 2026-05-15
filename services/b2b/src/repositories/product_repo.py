from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.product import Product
from .base import BaseRepository


class ProductRepository(BaseRepository[Product]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Product)

    async def get_with_skus(self, product_id: UUID) -> Product | None:
        result = await self.session.execute(
            select(Product)
            .where(Product.id == product_id)
            .options(selectinload(Product.skus))
        )
        return result.scalar_one_or_none()

    async def list_active(
        self,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
    ) -> tuple[list[Product], int]:
        base_query = select(Product).where(Product.is_active == True)  # noqa: E712
        if search:
            base_query = base_query.where(Product.title.ilike(f"%{search}%"))

        total = (
            await self.session.execute(
                select(func.count()).select_from(base_query.subquery())
            )
        ).scalar_one()

        items = (
            await self.session.execute(
                base_query
                .options(selectinload(Product.skus))
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()

        return list(items), total

    async def list_by_seller(self, seller_id: UUID) -> list[Product]:
        result = await self.session.execute(
            select(Product)
            .where(Product.seller_id == seller_id)
            .options(selectinload(Product.skus))
        )
        return list(result.scalars().all())

    async def get_seller_product(self, product_id: UUID, seller_id: UUID) -> Product | None:
        result = await self.session.execute(
            select(Product)
            .where(Product.id == product_id, Product.seller_id == seller_id)
            .options(selectinload(Product.skus))
        )
        return result.scalar_one_or_none()

    async def create_product(
        self,
        *,
        seller_id: UUID,
        title: str,
        description: str | None,
        category_id: UUID,
        images: list[str],
        characteristics: dict[str, object],
        category: str | None = None,
    ) -> Product:
        product = Product(
            seller_id=seller_id,
            title=title,
            description=description,
            category_id=category_id,
            images=images,
            characteristics=characteristics,
            category=category,
        )
        self.session.add(product)
        await self.session.flush()
        return product
