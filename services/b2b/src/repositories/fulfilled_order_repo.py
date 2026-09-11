from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.fulfilled_order import FulfilledOrder
from .base import BaseRepository


class FulfilledOrderRepository(BaseRepository[FulfilledOrder]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, FulfilledOrder)

    async def exists(self, order_id: UUID) -> bool:
        result = await self.session.execute(
            select(FulfilledOrder.id).where(FulfilledOrder.order_id == order_id)
        )
        return result.scalar_one_or_none() is not None

    async def mark_fulfilled(self, order_id: UUID) -> None:
        self.session.add(FulfilledOrder(order_id=order_id))
        await self.session.flush()
