from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.favorite import Favorite

from .base import BaseRepository


class FavoriteRepository(BaseRepository[Favorite]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Favorite)

    async def list_by_user(self, user_id: UUID) -> list[Favorite]:
        result = await self.session.execute(
            select(Favorite)
            .where(Favorite.user_id == user_id)
            .order_by(Favorite.added_at.desc())
        )
        return list(result.scalars().all())

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
