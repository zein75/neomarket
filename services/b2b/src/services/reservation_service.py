from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException, status
import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from src.clients.b2c import B2CClient
from src.models.reservation import Reservation
from src.repositories.fulfilled_order_repo import FulfilledOrderRepository
from src.repositories.reservation_operation_repo import ReservationOperationRepository
from src.repositories.reservation_repo import ReservationRepository
from src.repositories.sku_repo import SKURepository
from src.schemas.reservation import (
    FulfillRequest,
    ReservationCreate,
    ReserveRequest,
    UnreserveRequest,
)


class ReservationService:
    def __init__(self, session: AsyncSession) -> None:
        self.reservation_repo = ReservationRepository(session)
        self.reservation_operation_repo = ReservationOperationRepository(session)
        self.sku_repo = SKURepository(session)
        self.fulfilled_order_repo = FulfilledOrderRepository(session)

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

    async def reserve(self, data: ReserveRequest) -> dict[str, object]:
        idempotency_key = str(data.idempotency_key)
        existing = await self.reservation_operation_repo.get_by_idempotency_key(
            idempotency_key
        )
        if existing:
            return {
                "status": "RESERVED",
                "order_id": existing.order_id,
                "reserved_at": getattr(
                    existing,
                    "created_at",
                    datetime.now(timezone.utc),
                ),
            }

        sku_ids = [item.sku_id for item in data.items]
        if len(set(sku_ids)) != len(sku_ids):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "INVALID_REQUEST",
                    "message": "Duplicate SKU in reservation",
                },
            )

        skus = await self.sku_repo.list_for_update(sku_ids)
        skus_by_id = {sku.id: sku for sku in skus}
        if len(skus_by_id) != len(sku_ids):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "SKU_UNAVAILABLE",
                    "message": "One or more SKUs are unavailable",
                },
            )

        insufficient_skus = []
        for item in data.items:
            sku = skus_by_id[item.sku_id]
            if not sku.is_active or self._active_quantity(sku) < item.quantity:
                insufficient_skus.append(str(item.sku_id))

        if insufficient_skus:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "INSUFFICIENT_STOCK",
                    "message": "Insufficient stock",
                },
            )

        out_of_stock_skus = []
        for item in data.items:
            sku = skus_by_id[item.sku_id]
            sku.reserved_quantity += item.quantity
            if self._active_quantity(sku) == 0:
                out_of_stock_skus.append(sku)

        await self.sku_repo.session.flush()
        await self.reservation_repo.create_batch(
            order_id=data.order_id,
            idempotency_key=idempotency_key,
            items=data.items,
        )
        operation = await self.reservation_operation_repo.create(
            idempotency_key=idempotency_key,
            order_id=data.order_id,
        )
        for sku in out_of_stock_skus:
            try:
                await B2CClient().send_sku_out_of_stock(sku)
            except httpx.HTTPError:
                pass
        return {
            "status": "RESERVED",
            "order_id": data.order_id,
            "reserved_at": getattr(
                operation,
                "created_at",
                datetime.now(timezone.utc),
            ),
        }

    async def unreserve(self, data: UnreserveRequest) -> dict[str, object]:
        reservations = await self.reservation_repo.list_by_order(data.order_id)
        if not reservations:
            return {
                "status": "UNRESERVED",
                "order_id": data.order_id,
                "processed_at": datetime.now(timezone.utc),
            }

        skus = await self.sku_repo.list_for_update(
            [reservation.sku_id for reservation in reservations]
        )
        skus_by_id = {sku.id: sku for sku in skus}
        for reservation in reservations:
            sku = skus_by_id.get(reservation.sku_id)
            if sku:
                sku.reserved_quantity = max(
                    sku.reserved_quantity - reservation.quantity,
                    0,
                )
        await self.reservation_repo.delete_many(reservations)
        await self.reservation_repo.session.flush()
        return {
            "status": "UNRESERVED",
            "order_id": data.order_id,
            "processed_at": datetime.now(timezone.utc),
        }

    async def fulfill(self, data: FulfillRequest) -> dict[str, object]:
        if await self.fulfilled_order_repo.exists(data.order_id):
            return {
                "status": "FULFILLED",
                "order_id": data.order_id,
                "processed_at": datetime.now(timezone.utc),
            }

        reservations = await self.reservation_repo.list_by_order(data.order_id)
        if not reservations:
            return {
                "status": "FULFILLED",
                "order_id": data.order_id,
                "processed_at": datetime.now(timezone.utc),
            }

        skus = await self.sku_repo.list_for_update(
            [reservation.sku_id for reservation in reservations]
        )
        skus_by_id = {sku.id: sku for sku in skus}
        for reservation in reservations:
            sku = skus_by_id.get(reservation.sku_id)
            if sku:
                sku.stock = max(sku.stock - reservation.quantity, 0)
                sku.reserved_quantity = max(
                    sku.reserved_quantity - reservation.quantity,
                    0,
                )
        await self.reservation_repo.delete_many(reservations)
        await self.fulfilled_order_repo.mark_fulfilled(data.order_id)
        await self.reservation_repo.session.flush()
        return {
            "status": "FULFILLED",
            "order_id": data.order_id,
            "processed_at": datetime.now(timezone.utc),
        }

    async def cancel_by_order(self, order_id: UUID) -> None:
        await self.unreserve(UnreserveRequest(order_id=order_id))

    def _active_quantity(self, sku: object) -> int:
        return max(sku.stock - getattr(sku, "reserved_quantity", 0), 0)
