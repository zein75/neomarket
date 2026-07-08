from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.reservation import Reservation
from src.repositories.reservation_repo import ReservationRepository
from src.repositories.sku_repo import SKURepository
from src.schemas.reservation import ReservationCreate


class ReservationService:
    def __init__(self, session: AsyncSession) -> None:
        self.reservation_repo = ReservationRepository(session)
        self.sku_repo = SKURepository(session)

    async def create(self, data: ReservationCreate) -> Reservation:
        sku = await self.sku_repo.get_by_id(data.sku_id)
        if not sku or not sku.is_active:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="SKU not found"
            )
        if sku.stock < data.quantity:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Insufficient stock"
            )
        sku.stock -= data.quantity
        await self.sku_repo.session.flush()
        return await self.reservation_repo.create(
            sku_id=data.sku_id,
            order_id=data.order_id,
            quantity=data.quantity,
        )

    async def cancel_by_order(self, order_id: UUID) -> None:
        reservations = await self.reservation_repo.list_by_order(order_id)
        for reservation in reservations:
            sku = await self.sku_repo.get_by_id(reservation.sku_id)
            if sku:
                sku.stock += reservation.quantity
            await self.reservation_repo.delete(reservation)
        await self.reservation_repo.session.flush()
