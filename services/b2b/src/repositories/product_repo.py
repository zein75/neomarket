from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.category import Category
from src.models.product import Product
from src.models.sku import SKU
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
        base_query = select(Product).where(
            Product.is_active == True,  # noqa: E712
            Product.deleted == False,  # noqa: E712
        )
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
            .where(Product.seller_id == seller_id, Product.deleted == False)  # noqa: E712
            .options(selectinload(Product.skus))
        )
        return list(result.scalars().all())

    async def list_for_seller_cabinet(
        self,
        *,
        seller_id: UUID,
        limit: int,
        offset: int,
        status: str | None = None,
        include_deleted: bool = False,
        search: str | None = None,
    ) -> tuple[list[tuple[Product, int, int]], int]:
        sku_stats = (
            select(
                SKU.product_id.label("product_id"),
                func.count(SKU.id).label("skus_count"),
                func.coalesce(
                    func.sum(func.greatest(SKU.stock - SKU.reserved_quantity, 0)),
                    0,
                ).label("total_active_quantity"),
            )
            .group_by(SKU.product_id)
            .subquery()
        )
        base_query = select(Product).where(Product.seller_id == seller_id)
        if not include_deleted:
            base_query = base_query.where(Product.deleted == False)  # noqa: E712
        if status:
            base_query = base_query.where(Product.status == status)
        if search:
            base_query = base_query.where(Product.title.ilike(f"%{search}%"))

        total = (
            await self.session.execute(
                select(func.count()).select_from(base_query.subquery())
            )
        ).scalar_one()

        rows = (
            await self.session.execute(
                base_query
                .outerjoin(sku_stats, sku_stats.c.product_id == Product.id)
                .with_only_columns(
                    Product,
                    func.coalesce(sku_stats.c.skus_count, 0),
                    func.coalesce(sku_stats.c.total_active_quantity, 0),
                )
                .order_by(Product.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
        ).all()
        return [(row[0], int(row[1]), int(row[2])) for row in rows], total

    async def list_public_catalog(
        self,
        product_ids: list[UUID] | None = None,
    ) -> list[Product]:
        query = (
            select(Product)
            .where(
                Product.status == "MODERATED",
                Product.deleted == False,  # noqa: E712
            )
            .options(selectinload(Product.skus))
        )
        if product_ids is not None:
            query = query.where(Product.id.in_(product_ids))
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def category_exists(self, category_id: UUID) -> bool:
        result = await self.session.execute(
            select(Category.id).where(
                Category.id == category_id,
                Category.is_active == True,  # noqa: E712
            )
        )
        return result.scalar_one_or_none() is not None

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
        product_id = uuid4()
        product = Product(
            id=product_id,
            seller_id=seller_id,
            title=title,
            slug=Product.make_slug(title, product_id),
            description=description,
            category_id=category_id,
            images=images,
            characteristics=characteristics,
            category=category,
        )
        self.session.add(product)
        await self.session.flush()
        return product
