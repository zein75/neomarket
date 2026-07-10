from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.moderation import ModerationCard

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
