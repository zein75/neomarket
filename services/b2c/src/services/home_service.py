from datetime import date, datetime, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.clients.b2b_client import B2BClient
from src.core.config import settings
from src.repositories.home_repo import BannerRepository, CollectionRepository
from src.schemas.home import (
    BannerEventsCreate,
    BannerListResponse,
    CollectionListResponse,
    CollectionProductsResponse,
)


class HomeService:
    def __init__(self, session: AsyncSession) -> None:
        self.banner_repo = BannerRepository(session)
        self.collection_repo = CollectionRepository(session)

    async def list_banners(self) -> BannerListResponse:
        banners = await self.banner_repo.list_active(datetime.now(timezone.utc))
        return BannerListResponse(items=banners, total_count=len(banners))

    async def record_banner_events(
        self,
        data: BannerEventsCreate,
        *,
        user_id: UUID | None = None,
    ) -> dict[str, int]:
        if not data.events:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "EMPTY_EVENTS",
                    "message": "Events list must not be empty",
                },
        )

        for item in data.events:
            if not await self.banner_repo.exists(item.banner_id):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "code": "BANNER_NOT_FOUND",
                        "message": "Banner not found",
                    },
                )

        for item in data.events:
            await self.banner_repo.create_event(
                banner_id=item.banner_id,
                user_id=user_id,
                event=item.event,
                timestamp=item.timestamp,
            )
        return {"accepted": len(data.events)}

    async def list_collections(
        self,
        *,
        limit: int = 10,
        offset: int = 0,
    ) -> CollectionListResponse:
        collections, total = await self.collection_repo.list_active(
            today=date.today(),
            limit=limit,
            offset=offset,
        )
        return CollectionListResponse(
            items=collections,
            total_count=total,
            limit=limit,
            offset=offset,
        )

    async def collection_products(
        self,
        collection_id: UUID,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> CollectionProductsResponse:
        collection = await self.collection_repo.get_active(collection_id, date.today())
        if not collection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": "COLLECTION_NOT_FOUND",
                    "message": "Collection not found",
                },
            )

        product_ids, total_products = await self.collection_repo.list_product_ids(
            collection_id,
            limit=limit,
            offset=offset,
        )
        if not product_ids:
            return CollectionProductsResponse(
                collection_id=collection.id,
                collection_title=collection.title,
                items=[],
                unavailable_ids=[],
                total_products=0,
                limit=limit,
                offset=offset,
            )

        async with B2BClient(settings.b2b_base_url) as client:
            products = await client.get_products_batch(
                [str(product_id) for product_id in product_ids]
            )
        products_by_id = {
            str(product.get("id")): product
            for product in products
            if isinstance(product, dict) and product.get("id")
        }
        items = [
            products_by_id[str(product_id)]
            for product_id in product_ids
            if str(product_id) in products_by_id
        ]
        unavailable_ids = [
            product_id
            for product_id in product_ids
            if str(product_id) not in products_by_id
        ]
        return CollectionProductsResponse(
            collection_id=collection.id,
            collection_title=collection.title,
            items=items,
            unavailable_ids=unavailable_ids,
            total_products=total_products,
            limit=limit,
            offset=offset,
        )
