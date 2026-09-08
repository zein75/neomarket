from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.order import Order, OrderStatus, PendingFulfillment

from .base import BaseRepository


class OrderRepository(BaseRepository[Order]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Order)

    async def list_by_status(self, status: OrderStatus, limit: int = 100) -> list[Order]:
        result = await self.session.execute(
            select(Order)
            .where(Order.status == status)
            .options(selectinload(Order.items))
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_with_items(self, order_id: UUID) -> Order | None:
        result = await self.session.execute(
            select(Order)
            .where(Order.id == order_id)
            .options(selectinload(Order.items))
        )
        return result.scalar_one_or_none()

    async def get_with_items_for_update(self, order_id: UUID) -> Order | None:
        result = await self.session.execute(
            select(Order)
            .where(Order.id == order_id)
            .with_for_update()
            .options(selectinload(Order.items))
        )
        return result.scalar_one_or_none()

    async def get_user_order_with_items(
        self,
        order_id: UUID,
        user_id: UUID,
    ) -> Order | None:
        result = await self.session.execute(
            select(Order)
            .where(Order.id == order_id, Order.user_id == user_id)
            .options(selectinload(Order.items))
        )
        return result.scalar_one_or_none()

    async def get_by_idempotency_key(self, idempotency_key: str) -> Order | None:
        result = await self.session.execute(
            select(Order)
            .where(Order.idempotency_key == idempotency_key)
            .options(selectinload(Order.items))
        )
        return result.scalar_one_or_none()

    async def list_by_user(self, user_id: UUID) -> list[Order]:
        result = await self.session.execute(
            select(Order)
            .where(Order.user_id == user_id)
            .options(selectinload(Order.items))
            .order_by(Order.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_for_user(
        self,
        user_id: UUID,
        *,
        limit: int,
        offset: int,
        status_filter: OrderStatus | None = None,
    ) -> tuple[list[Order], int]:
        filters = [Order.user_id == user_id]
        if status_filter is not None:
            filters.append(Order.status == status_filter)

        total_result = await self.session.execute(
            select(func.count()).select_from(Order).where(*filters)
        )
        total_count = int(total_result.scalar_one())

        result = await self.session.execute(
            select(Order)
            .where(*filters)
            .options(selectinload(Order.items))
            .order_by(Order.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all()), total_count

    async def get_pending_fulfillment(
        self,
        order_id: UUID,
    ) -> PendingFulfillment | None:
        result = await self.session.execute(
            select(PendingFulfillment).where(PendingFulfillment.order_id == order_id)
        )
        return result.scalar_one_or_none()

    async def queue_fulfillment_retry(
        self,
        order: Order,
        error: str,
    ) -> PendingFulfillment:
        pending = await self.get_pending_fulfillment(order.id)
        if pending is None:
            pending = PendingFulfillment(order_id=order.id, attempts=1, last_error=error)
            self.session.add(pending)
        else:
            pending.attempts += 1
            pending.last_error = error
        await self.session.flush()
        return pending

    async def list_pending_fulfillments(
        self,
        *,
        limit: int = 100,
    ) -> list[PendingFulfillment]:
        result = await self.session.execute(
            select(PendingFulfillment)
            .options(selectinload(PendingFulfillment.order).selectinload(Order.items))
            .order_by(PendingFulfillment.updated_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def delete_pending_fulfillment(
        self,
        pending: PendingFulfillment,
    ) -> None:
        await self.session.delete(pending)
        await self.session.flush()
