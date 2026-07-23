from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.reservation_operation import ReservationOperation
from .base import BaseRepository


class ReservationOperationRepository(BaseRepository[ReservationOperation]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, ReservationOperation)

    async def get_by_idempotency_key(
        self, idempotency_key: str
    ) -> ReservationOperation | None:
        result = await self.session.execute(
            select(ReservationOperation).where(
                ReservationOperation.idempotency_key == idempotency_key
            )
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        idempotency_key: str,
        order_id: UUID,
    ) -> ReservationOperation:
        operation = ReservationOperation(
            idempotency_key=idempotency_key,
            order_id=order_id,
        )
        self.session.add(operation)
        await self.session.flush()
        await self.session.refresh(operation)
        return operation
