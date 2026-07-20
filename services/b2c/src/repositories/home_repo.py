from datetime import date, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.home import Banner, BannerEvent, Collection, CollectionProduct

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


class CollectionRepository(BaseRepository[Collection]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Collection)

    async def list_active(
        self,
        *,
        today: date,
        limit: int,
        offset: int,
    ) -> tuple[list[Collection], int]:
        base_query = select(Collection).where(
            Collection.is_active == True,  # noqa: E712
            (Collection.start_date.is_(None)) | (Collection.start_date <= today),
        )
        total = (
            await self.session.execute(
                select(func.count()).select_from(base_query.subquery())
            )
        ).scalar_one()
        rows = (
            await self.session.execute(
                base_query
                .order_by(Collection.priority.asc(), Collection.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
        ).scalars().all()
        return list(rows), int(total)

    async def get_active(self, collection_id: UUID, today: date) -> Collection | None:
        result = await self.session.execute(
            select(Collection).where(
                Collection.id == collection_id,
                Collection.is_active == True,  # noqa: E712
                (Collection.start_date.is_(None)) | (Collection.start_date <= today),
            )
        )
        return result.scalar_one_or_none()

    async def list_product_ids(
        self,
        collection_id: UUID,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[UUID], int]:
        total = (
            await self.session.execute(
                select(func.count()).select_from(
                    select(CollectionProduct.product_id)
                    .where(CollectionProduct.collection_id == collection_id)
                    .subquery()
                )
            )
        ).scalar_one()
        rows = (
            await self.session.execute(
                select(CollectionProduct.product_id)
                .where(CollectionProduct.collection_id == collection_id)
                .order_by(CollectionProduct.ordering.asc())
                .offset(offset)
                .limit(limit)
            )
        ).scalars().all()
        return list(rows), int(total)
