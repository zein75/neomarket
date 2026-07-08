from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db
from src.schemas.reservation import ReservationCreate, ReservationResponse
from src.services.reservation_service import ReservationService

router = APIRouter(prefix="/reservations", tags=["reservations"])


@router.post("", response_model=ReservationResponse, status_code=201)
async def create_reservation(
    data: ReservationCreate,
    db: AsyncSession = Depends(get_db),
) -> Any:
    svc = ReservationService(db)
    reservation = await svc.create(data)
    await db.commit()
    await db.refresh(reservation)
    return reservation


@router.delete("/{order_id}", status_code=204)
async def cancel_reservations(
    order_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    svc = ReservationService(db)
    await svc.cancel_by_order(order_id)
    await db.commit()
