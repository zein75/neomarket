from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.favorite import Favorite, ProductSubscription

from .base import BaseRepository


class FavoriteRepository(BaseRepository[Favorite]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Favorite)

    async def list_by_user(
        self,
        user_id: UUID,
        *,
        limit: int,
        offset: int,
    ) -> list[Favorite]:
        result = await self.session.execute(
            select(Favorite)
            .where(Favorite.user_id == user_id)
            .order_by(Favorite.added_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def count_by_user(self, user_id: UUID) -> int:
        result = await self.session.execute(
            select(Favorite.id).where(Favorite.user_id == user_id)
        )
        return len(result.scalars().all())

    async def get_by_user_and_product(
        self, user_id: UUID, product_id: UUID
    ) -> Favorite | None:
        result = await self.session.execute(
            select(Favorite).where(
                Favorite.user_id == user_id,
                Favorite.product_id == product_id,
            )
        )
        return result.scalar_one_or_none()


class ProductSubscriptionRepository(BaseRepository[ProductSubscription]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, ProductSubscription)

    async def get_by_user_and_product(
        self,
        user_id: UUID,
        product_id: UUID,
    ) -> ProductSubscription | None:
        result = await self.session.execute(
            select(ProductSubscription).where(
                ProductSubscription.user_id == user_id,
                ProductSubscription.product_id == product_id,
            )
        )
        return result.scalar_one_or_none()
