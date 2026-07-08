from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.reservation import Reservation
from src.schemas.reservation import ReserveItem
from .base import BaseRepository


class ReservationRepository(BaseRepository[Reservation]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Reservation)

    async def list_by_order(self, order_id: UUID) -> list[Reservation]:
        result = await self.session.execute(
            select(Reservation).where(Reservation.order_id == order_id)
        )
        return list(result.scalars().all())

    async def get_by_idempotency_key(self, idempotency_key: str) -> Reservation | None:
        result = await self.session.execute(
            select(Reservation).where(Reservation.idempotency_key == idempotency_key)
        )
        return result.scalars().first()

    async def create_batch(
        self,
        *,
        order_id: UUID,
        idempotency_key: str,
        items: list[ReserveItem],
    ) -> list[Reservation]:
        reservations = [
            Reservation(
                sku_id=item.sku_id,
                order_id=order_id,
                quantity=item.quantity,
                idempotency_key=idempotency_key,
            )
            for item in items
        ]
        self.session.add_all(reservations)
        await self.session.flush()
        return reservations

    async def delete_many(self, reservations: list[Reservation]) -> None:
        for reservation in reservations:
            await self.session.delete(reservation)
        await self.session.flush()
