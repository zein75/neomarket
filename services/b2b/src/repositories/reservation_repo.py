from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.reservation import Reservation
from .base import BaseRepository


class ReservationRepository(BaseRepository[Reservation]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Reservation)

    async def list_by_order(self, order_id: UUID) -> list[Reservation]:
        result = await self.session.execute(
            select(Reservation).where(Reservation.order_id == order_id)
        )
        return list(result.scalars().all())
