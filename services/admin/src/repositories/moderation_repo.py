from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.moderation import BlockingReason, ModerationCard, ModerationStatus

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

    async def get_with_skus_for_update(self, card_id: UUID) -> ModerationCard | None:
        result = await self.session.execute(
            select(ModerationCard)
            .where(ModerationCard.id == card_id)
            .options(selectinload(ModerationCard.skus))
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_by_product_id(self, product_id: UUID) -> ModerationCard | None:
        result = await self.session.execute(
            select(ModerationCard)
            .where(ModerationCard.product_id == product_id)
            .order_by(ModerationCard.submitted_revision.desc().nullslast(), ModerationCard.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_by_product_id_for_update(self, product_id: UUID) -> ModerationCard | None:
        result = await self.session.execute(
            select(ModerationCard)
            .where(ModerationCard.product_id == product_id)
            .order_by(ModerationCard.submitted_revision.desc().nullslast(), ModerationCard.created_at.desc())
            .limit(1)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def list_tickets_keyset(
        self,
        *,
        limit: int,
        status: ModerationStatus | None = None,
        priority: int | None = None,
        seller_id: UUID | None = None,
        seller_ids: set[UUID] | None = None,
        cursor: tuple[int, datetime, UUID] | None = None,
    ) -> tuple[list[ModerationCard], bool]:
        query = select(ModerationCard)
        if status is not None:
            query = query.where(ModerationCard.status == status)
        if priority is not None:
            query = query.where(ModerationCard.queue_priority == priority)
        if seller_id is not None:
            query = query.where(ModerationCard.seller_id == seller_id)
        elif seller_ids is not None:
            if not seller_ids:
                return [], False
            query = query.where(ModerationCard.seller_id.in_(seller_ids))
        if cursor is not None:
            priority, created_at, card_id = cursor
            query = query.where(
                or_(
                    ModerationCard.queue_priority < priority,
                    and_(ModerationCard.queue_priority == priority, ModerationCard.created_at > created_at),
                    and_(
                        ModerationCard.queue_priority == priority,
                        ModerationCard.created_at == created_at,
                        ModerationCard.id > card_id,
                    ),
                )
            )
        result = await self.session.execute(
            query.order_by(
                ModerationCard.queue_priority.desc(),
                ModerationCard.created_at.asc(),
                ModerationCard.id.asc(),
            ).limit(limit + 1)
        )
        rows = list(result.scalars().all())
        return rows[:limit], len(rows) > limit

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
