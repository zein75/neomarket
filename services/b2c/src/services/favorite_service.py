from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.favorite import Favorite
from src.repositories.favorite_repo import FavoriteRepository
from src.schemas.favorite import FavoriteAdd


class FavoriteService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = FavoriteRepository(session)

    async def list_favorites(self, user_id: UUID) -> list[Favorite]:
        return await self.repo.list_by_user(user_id)

    async def add_favorite(self, user_id: UUID, data: FavoriteAdd) -> Favorite:
        existing = await self.repo.get_by_user_and_product(user_id, data.product_id)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Already in favorites",
            )
        return await self.repo.create(user_id=user_id, product_id=data.product_id)

    async def remove_favorite(self, user_id: UUID, product_id: UUID) -> None:
        fav = await self.repo.get_by_user_and_product(user_id, product_id)
        if not fav:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Favorite not found",
            )
        await self.repo.delete(fav)
