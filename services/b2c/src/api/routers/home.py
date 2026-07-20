from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db, get_optional_user
from src.models.user import User
from src.schemas.home import BannerEventsCreate, BannerEventsResponse, BannerListResponse
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
