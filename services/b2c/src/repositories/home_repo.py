from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.home import Banner, BannerEvent

from .base import BaseRepository


class BannerRepository(BaseRepository[Banner]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Banner)

    async def list_active(self, now: datetime) -> list[Banner]:
        result = await self.session.execute(
            select(Banner)
            .where(
                Banner.is_active == True,  # noqa: E712
                (Banner.start_at.is_(None)) | (Banner.start_at <= now),
                (Banner.end_at.is_(None)) | (Banner.end_at >= now),
            )
            .order_by(Banner.priority.asc(), Banner.created_at.desc())
        )
        return list(result.scalars().all())

    async def exists(self, banner_id: UUID) -> bool:
        result = await self.session.execute(
            select(Banner.id).where(Banner.id == banner_id)
        )
        return result.scalar_one_or_none() is not None

    async def create_event(
        self,
        *,
        banner_id: UUID,
        user_id: UUID | None,
        event: str,
        timestamp: datetime,
    ) -> BannerEvent:
        return await super().create(
            banner_id=banner_id,
            user_id=user_id,
            event=event,
            timestamp=timestamp,
        )
