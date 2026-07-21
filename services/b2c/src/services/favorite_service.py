from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.clients.b2b_client import B2BClient
from src.core.config import settings
from src.models.favorite import Favorite, ProductSubscription
from src.repositories.favorite_repo import (
    FavoriteRepository,
    ProductSubscriptionRepository,
)
from src.schemas.favorite import ProductSubscriptionRequest


ALLOWED_NOTIFY_ON = {"IN_STOCK", "PRICE_DOWN"}


class FavoriteService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = FavoriteRepository(session)
        self.subscription_repo = ProductSubscriptionRepository(session)

    async def list_favorites(
        self,
        user_id: UUID,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, object]:
        favorites = await self.repo.list_by_user(user_id, limit=limit, offset=offset)
        total_count = await self.repo.count_by_user(user_id)
        if not favorites:
            return {
                "items": [],
                "total_count": total_count,
                "limit": limit,
                "offset": offset,
            }

        product_ids = [str(favorite.product_id) for favorite in favorites]
        try:
            async with B2BClient(settings.b2b_base_url) as client:
                products = await client.get_products_batch(product_ids)
        except HTTPException as exc:
            if exc.status_code == status.HTTP_503_SERVICE_UNAVAILABLE:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail={
                        "code": "B2B_UNAVAILABLE",
                        "message": "Product service is temporarily unavailable",
                    },
                ) from exc
            raise
        visible_products = {
            str(product.get("id")): product
            for product in products
            if isinstance(product, dict) and product.get("id")
        }

        return {
            "items": [
                {
                    "id": favorite.id,
                    "product_id": favorite.product_id,
                    "added_at": favorite.added_at,
                    "product": visible_products[str(favorite.product_id)],
                }
                for favorite in favorites
                if str(favorite.product_id) in visible_products
            ],
            "total_count": total_count,
            "limit": limit,
            "offset": offset,
        }

    async def add_favorite(self, user_id: UUID, product_id: UUID) -> tuple[Favorite, bool]:
        existing = await self.repo.get_by_user_and_product(user_id, product_id)
        if existing:
            return existing, False
        await self._ensure_product_exists(product_id)
        favorite = await self.repo.create(user_id=user_id, product_id=product_id)
        return favorite, True

    async def remove_favorite(self, user_id: UUID, product_id: UUID) -> None:
        fav = await self.repo.get_by_user_and_product(user_id, product_id)
        if fav:
            await self.repo.delete(fav)

    async def subscribe(
        self,
        user_id: UUID,
        product_id: UUID,
        data: ProductSubscriptionRequest,
    ) -> ProductSubscription:
        notify_on = self._validate_notify_on(data.notify_on)
        existing = await self.subscription_repo.get_by_user_and_product(
            user_id,
            product_id,
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "SUBSCRIPTION_ALREADY_EXISTS",
                    "message": "Subscription already exists",
                },
            )

        await self._ensure_product_exists(product_id)
        return await self.subscription_repo.create(
            user_id=user_id,
            product_id=product_id,
            notify_on=notify_on,
        )

    async def unsubscribe(self, user_id: UUID, product_id: UUID) -> None:
        subscription = await self.subscription_repo.get_by_user_and_product(
            user_id,
            product_id,
        )
        if subscription:
            await self.subscription_repo.delete(subscription)

    def _validate_notify_on(self, notify_on: list[str]) -> list[str]:
        if not notify_on:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "INVALID_NOTIFY_ON",
                    "message": "notify_on must contain at least one event type",
                },
            )
        normalized = list(dict.fromkeys(notify_on))
        invalid = [value for value in normalized if value not in ALLOWED_NOTIFY_ON]
        if invalid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "INVALID_NOTIFY_ON",
                    "message": "notify_on contains unsupported event type",
                },
            )
        return normalized

    async def _ensure_product_exists(self, product_id: UUID) -> None:
        async with B2BClient(settings.b2b_base_url) as client:
            try:
                await client.get_product(str(product_id))
            except HTTPException as exc:
                if exc.status_code == status.HTTP_404_NOT_FOUND:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail={
                            "code": "PRODUCT_NOT_FOUND",
                            "message": "Product not found",
                        },
                    )
                if exc.status_code == status.HTTP_503_SERVICE_UNAVAILABLE:
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail={
                            "code": "B2B_UNAVAILABLE",
                            "message": "Product service is temporarily unavailable",
                        },
                    )
                raise
