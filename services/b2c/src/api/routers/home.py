from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi import Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db, get_optional_user
from src.models.user import User
from src.schemas.home import (
    BannerEventsCreate,
    BannerEventsResponse,
    BannerListResponse,
    CollectionListResponse,
    CollectionProductsResponse,
)
from src.services.home_service import HomeService


router = APIRouter(tags=["home"])


@router.get("/api/v1/home/banners", response_model=BannerListResponse)
async def list_banners(
    db: AsyncSession = Depends(get_db),
) -> BannerListResponse:
    return await HomeService(db).list_banners()


@router.post("/api/v1/banner-events", response_model=BannerEventsResponse)
async def record_banner_events(
    data: BannerEventsCreate,
    current_user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    result = await HomeService(db).record_banner_events(
        data,
        user_id=current_user.id if current_user else None,
    )
    await db.commit()
    return result


@router.get("/api/v1/main/collections", response_model=CollectionListResponse)
async def list_collections(
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> CollectionListResponse:
    return await HomeService(db).list_collections(limit=limit, offset=offset)


@router.get(
    "/api/v1/collections/{collection_id}/products",
    response_model=CollectionProductsResponse,
)
async def collection_products(
    collection_id: UUID,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> CollectionProductsResponse:
    return await HomeService(db).collection_products(
        collection_id,
        limit=limit,
        offset=offset,
    )
