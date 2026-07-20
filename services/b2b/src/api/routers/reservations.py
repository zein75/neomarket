from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db, verify_service_key
from src.schemas.reservation import (
    FulfillRequest,
    InventoryFulfillResponse,
    InventoryReserveResponse,
    InventoryUnreserveResponse,
    ReservationCreate,
    ReservationResponse,
    ReserveRequest,
    UnreserveRequest,
)
from src.services.reservation_service import ReservationService

router = APIRouter(tags=["reservations"])


@router.post("/api/v1/reserve", response_model=InventoryReserveResponse)
async def reserve_inventory(
    data: ReserveRequest,
    _: None = Depends(verify_service_key),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    result = await ReservationService(db).reserve(data)
    await db.commit()
    return result


@router.post("/api/v1/inventory/reserve", response_model=InventoryReserveResponse)
async def reserve_inventory_alias(
    data: ReserveRequest,
    _: None = Depends(verify_service_key),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    return await reserve_inventory(data, _, db)


@router.post("/api/v1/unreserve", response_model=InventoryUnreserveResponse)
async def unreserve_inventory(
    data: UnreserveRequest,
    _: None = Depends(verify_service_key),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    result = await ReservationService(db).unreserve(data)
    await db.commit()
    return result


@router.post("/api/v1/inventory/unreserve", response_model=InventoryUnreserveResponse)
async def unreserve_inventory_alias(
    data: UnreserveRequest,
    _: None = Depends(verify_service_key),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    return await unreserve_inventory(data, _, db)


@router.post("/api/v1/fulfill", response_model=InventoryFulfillResponse)
async def fulfill_inventory(
    data: FulfillRequest,
    _: None = Depends(verify_service_key),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    result = await ReservationService(db).fulfill(data)
    await db.commit()
    return result


@router.post("/api/v1/inventory/fulfill", response_model=InventoryFulfillResponse)
async def fulfill_inventory_alias(
    data: FulfillRequest,
    _: None = Depends(verify_service_key),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    return await fulfill_inventory(data, _, db)


@router.post("/reservations", response_model=ReservationResponse, status_code=201)
async def create_reservation(
    data: ReservationCreate,
    db: AsyncSession = Depends(get_db),
) -> Any:
    svc = ReservationService(db)
    reservation = await svc.create(data)
    await db.commit()
    await db.refresh(reservation)
    return reservation


@router.delete("/reservations/{order_id}", status_code=204)
async def cancel_reservations(
    order_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    svc = ReservationService(db)
    await svc.cancel_by_order(order_id)
    await db.commit()
