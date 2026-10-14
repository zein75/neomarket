from fastapi import APIRouter, Depends, HTTPException, status
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db, verify_service_key
from src.schemas.reservation import (
    FulfillRequest,
    InventoryFulfillResponse,
    InventoryReserveResponse,
    InventoryUnreserveResponse,
    ReserveRequest,
    UnreserveRequest,
)
from src.services.reservation_service import ReservationService
from src.models.inventory_order_lifecycle import InventoryOrderLifecycle

router = APIRouter(tags=["reservations"])


@router.get("/internal/v1/inventory/orders/{order_id}")
async def get_inventory_order(
    order_id: UUID,
    _: None = Depends(verify_service_key),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    lifecycle = await db.scalar(
        select(InventoryOrderLifecycle).where(InventoryOrderLifecycle.order_id == order_id)
    )
    if lifecycle is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "INVENTORY_ORDER_NOT_FOUND", "message": "Inventory order not found"},
        )
    return {
        "order_id": str(lifecycle.order_id),
        "state": lifecycle.state,
        "version": lifecycle.version,
        "result": lifecycle.result,
        "updated_at": lifecycle.updated_at,
    }


@router.post(
    "/internal/v1/inventory/reserve",
    response_model=InventoryReserveResponse,
    status_code=status.HTTP_201_CREATED,
    responses={200: {"model": InventoryReserveResponse, "description": "Already reserved"}},
)
@router.post("/api/v1/inventory/reserve", response_model=InventoryReserveResponse, include_in_schema=False)
async def reserve_inventory(
    data: ReserveRequest,
    _: None = Depends(verify_service_key),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    result = await ReservationService(db).reserve(data)
    await db.commit()
    return result


@router.post(
    "/api/v1/reserve",
    response_model=InventoryReserveResponse,
    include_in_schema=False,
)
async def reserve_inventory_legacy_alias(
    data: ReserveRequest,
    _: None = Depends(verify_service_key),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    return await reserve_inventory(data, _, db)


@router.post("/internal/v1/inventory/unreserve", response_model=InventoryUnreserveResponse)
@router.post("/api/v1/inventory/unreserve", response_model=InventoryUnreserveResponse, include_in_schema=False)
async def unreserve_inventory(
    data: UnreserveRequest,
    _: None = Depends(verify_service_key),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    result = await ReservationService(db).unreserve(data)
    await db.commit()
    return result


@router.post(
    "/api/v1/unreserve",
    response_model=InventoryUnreserveResponse,
    include_in_schema=False,
)
async def unreserve_inventory_legacy_alias(
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


@router.post("/internal/v1/inventory/fulfill", response_model=InventoryFulfillResponse)
@router.post("/api/v1/inventory/fulfill", response_model=InventoryFulfillResponse, include_in_schema=False)
async def fulfill_inventory_alias(
    data: FulfillRequest,
    _: None = Depends(verify_service_key),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    return await fulfill_inventory(data, _, db)
