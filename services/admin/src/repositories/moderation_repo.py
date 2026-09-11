from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.moderation import BlockingReason, ModerationCard

from .base import BaseRepository


class ModerationRepository(BaseRepository[ModerationCard]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, ModerationCard)

    async def get_with_skus(self, card_id: UUID) -> ModerationCard | None:
        result = await self.session.execute(
            select(ModerationCard)
            .where(ModerationCard.id == card_id)
            .options(selectinload(ModerationCard.skus))
        )
        return result.scalar_one_or_none()

    async def get_by_product_id(self, product_id: UUID) -> ModerationCard | None:
        result = await self.session.execute(
            select(ModerationCard).where(ModerationCard.product_id == product_id)
        )
        return result.scalar_one_or_none()

    async def delete(self, card: ModerationCard) -> None:
        await self.session.delete(card)
        await self.session.flush()

    async def list_blocking_reasons(
        self,
        reason_ids: list[UUID],
    ) -> list[BlockingReason]:
        result = await self.session.execute(
            select(BlockingReason).where(
                BlockingReason.id.in_(reason_ids),
                BlockingReason.is_active.is_(True),
            )
        )
        return list(result.scalars().all())

    async def list_all_blocking_reasons(
        self,
        *,
        hard_block: bool | None = None,
    ) -> list[BlockingReason]:
        query = select(BlockingReason).where(BlockingReason.is_active.is_(True))
        if hard_block is not None:
            query = query.where(BlockingReason.hard_block.is_(hard_block))
        result = await self.session.execute(query.order_by(BlockingReason.title))
        return list(result.scalars().all())
