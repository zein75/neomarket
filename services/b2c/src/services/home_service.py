from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.repositories.home_repo import BannerRepository
from src.schemas.home import BannerEventsCreate, BannerListResponse


class HomeService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = BannerRepository(session)

    async def list_banners(self) -> BannerListResponse:
        banners = await self.repo.list_active(datetime.now(timezone.utc))
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
            if not await self.repo.exists(item.banner_id):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "code": "BANNER_NOT_FOUND",
                        "message": "Banner not found",
                    },
                )

        for item in data.events:
            await self.repo.create_event(
                banner_id=item.banner_id,
                user_id=user_id,
                event=item.event,
                timestamp=item.timestamp,
            )
        return {"accepted": len(data.events)}
