from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.clients.b2b_client import B2BClient
from src.core.config import settings
from src.models.favorite import Favorite
from src.repositories.favorite_repo import FavoriteRepository
from src.schemas.favorite import FavoriteAdd


class FavoriteService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = FavoriteRepository(session)

    async def list_favorites(self, user_id: UUID) -> list[dict[str, object]]:
        favorites = await self.repo.list_by_user(user_id)
        if not favorites:
            return []

        product_ids = [str(favorite.product_id) for favorite in favorites]
        async with B2BClient(settings.b2b_base_url) as client:
            products = await client.get_products_batch(product_ids)
        visible_products = {
            str(product.get("id")): product
            for product in products
            if isinstance(product, dict) and product.get("id")
        }

        return [
            {
                "id": favorite.id,
                "product_id": favorite.product_id,
                "added_at": favorite.added_at,
                "product": visible_products[str(favorite.product_id)],
            }
            for favorite in favorites
            if str(favorite.product_id) in visible_products
        ]

    async def add_favorite(self, user_id: UUID, data: FavoriteAdd) -> tuple[Favorite, bool]:
        existing = await self.repo.get_by_user_and_product(user_id, data.product_id)
        if existing:
            return existing, False
        favorite = await self.repo.create(user_id=user_id, product_id=data.product_id)
        return favorite, True

    async def remove_favorite(self, user_id: UUID, product_id: UUID) -> None:
        fav = await self.repo.get_by_user_and_product(user_id, product_id)
        if fav:
            await self.repo.delete(fav)
