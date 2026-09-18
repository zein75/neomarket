from datetime import datetime, timezone
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.clients.b2c import B2CClient
from src.models.reservation import Reservation
from src.models.product import ProductStatus
from src.repositories.fulfilled_order_repo import FulfilledOrderRepository
from src.repositories.reservation_operation_repo import ReservationOperationRepository
from src.repositories.reservation_repo import ReservationRepository
from src.repositories.outbox_event_repo import OutboxEventRepository
from src.repositories.sku_repo import SKURepository
from src.schemas.reservation import (
    FulfillRequest,
    ReservationCreate,
    ReserveRequest,
    ReserveItem,
    UnreserveRequest,
)


class ReservationService:
    def __init__(self, session: AsyncSession) -> None:
        self.reservation_repo = ReservationRepository(session)
        self.reservation_operation_repo = ReservationOperationRepository(session)
        self.sku_repo = SKURepository(session)
        self.fulfilled_order_repo = FulfilledOrderRepository(session)
        self.outbox_repo = OutboxEventRepository(session)

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
            return await self._reservation_result(existing)

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

        # Re-check after the SKU locks: a concurrent retry may have completed
        # the same idempotent operation while this request was waiting.
        existing = await self.reservation_operation_repo.get_by_idempotency_key(
            idempotency_key
        )
        if existing:
            return await self._reservation_result(existing)

        failed_items = []
        for item in data.items:
            sku = skus_by_id[item.sku_id]
            product = getattr(sku, "product", None)
            product_status = getattr(product, "status", None)
            available = self._active_quantity(sku)
            if (
                not sku.is_active
                or product_status != ProductStatus.MODERATED
                or getattr(product, "deleted", False)
                or getattr(sku, "deleted", False)
                or available < item.quantity
            ):
                failed_items.append(
                    {
                        "sku_id": str(item.sku_id),
                        "requested": item.quantity,
                        "available": available,
                        "reason": "OUT_OF_STOCK" if available == 0 else "INSUFFICIENT_STOCK",
                    }
                )

        if failed_items:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "INSUFFICIENT_STOCK",
                    "message": "Insufficient stock",
                    "reserved": False,
                    "failed_items": failed_items,
                },
            )

        out_of_stock_skus = []
        response_items = []
        for item in data.items:
            sku = skus_by_id[item.sku_id]
            sku.reserved_quantity += item.quantity
            response_items.append(
                {
                    "sku_id": sku.id,
                    "reserved_quantity": item.quantity,
                    "remaining_stock": self._active_quantity(sku),
                }
            )
            if self._active_quantity(sku) == 0:
                out_of_stock_skus.append(sku)

        try:
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
                event = {
                    "event": "SKU_OUT_OF_STOCK",
                    "idempotency_key": str(
                        uuid5(
                            NAMESPACE_URL,
                            f"sku-out-of-stock:{idempotency_key}:{sku.id}",
                        )
                    ),
                    "date": datetime.now(timezone.utc).isoformat(),
                    "product_id": str(sku.product_id),
                    "sku_ids": [str(sku.id)],
                }
                await self.outbox_repo.create_b2c_event(
                    idempotency_key=event["idempotency_key"],
                    event_type=event["event"],
                    payload={
                        "event_type": event["event"],
                        "idempotency_key": event["idempotency_key"],
                        "occurred_at": event["date"],
                        "payload": {
                            "product_id": event["product_id"],
                            "sku_id": event["sku_ids"][0],
                            "available_quantity": 0,
                        },
                    },
                )
        except IntegrityError:
            rollback = getattr(self.reservation_operation_repo.session, "rollback", None)
            if rollback:
                await rollback()
            existing = await self.reservation_operation_repo.get_by_idempotency_key(
                idempotency_key
            )
            if not existing:
                raise
            return await self._reservation_result(existing)
        for sku in out_of_stock_skus:
            try:
                await B2CClient().send_sku_out_of_stock(sku)
            except Exception:  # noqa: BLE001 - the committed outbox is the retry source
                pass
        return {
            "status": "RESERVED",
            "order_id": data.order_id,
            "reserved_at": getattr(
                operation,
                "created_at",
                datetime.now(timezone.utc),
            ),
            "reserved": True,
            "items": response_items,
        }

    async def _reservation_result(self, operation: object) -> dict[str, object]:
        reservations = await self.reservation_repo.list_by_order(operation.order_id)
        sku_ids = [reservation.sku_id for reservation in reservations]
        skus = await self.sku_repo.list_for_update(sku_ids) if sku_ids else []
        skus_by_id = {sku.id: sku for sku in skus}
        return {
            "status": "RESERVED",
            "order_id": operation.order_id,
            "reserved_at": getattr(
                operation,
                "created_at",
                datetime.now(timezone.utc),
            ),
            "reserved": True,
            "items": [
                {
                    "sku_id": reservation.sku_id,
                    "reserved_quantity": reservation.quantity,
                    "remaining_stock": self._active_quantity(
                        skus_by_id[reservation.sku_id]
                    )
                    if reservation.sku_id in skus_by_id
                    else 0,
                }
                for reservation in reservations
            ],
        }

    async def unreserve(self, data: UnreserveRequest) -> dict[str, object]:
        reservations = await self.reservation_repo.list_by_order(data.order_id)
        if not reservations:
            return {
                "status": "UNRESERVED",
                "order_id": data.order_id,
                "processed_at": datetime.now(timezone.utc),
            }

        sku_ids = [item.sku_id for item in data.items]
        if len(set(sku_ids)) != len(sku_ids):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "INVALID_REQUEST",
                    "message": "Duplicate SKU in unreserve",
                },
            )

        skus = await self.sku_repo.list_for_update(
            sku_ids
        )
        skus_by_id = {sku.id: sku for sku in skus}
        reservations_by_sku = {
            reservation.sku_id: reservation for reservation in reservations
        }
        for item in data.items:
            sku = skus_by_id.get(item.sku_id)
            reservation = reservations_by_sku.get(item.sku_id)
            if sku is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "code": "SKU_UNAVAILABLE",
                        "message": "One or more SKUs are unavailable",
                    },
                )
            if reservation is None or reservation.quantity < item.quantity:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "code": "INSUFFICIENT_RESERVATION",
                        "message": "Cannot unreserve more than reserved",
                    },
                )

        to_delete = []
        for item in data.items:
            sku = skus_by_id[item.sku_id]
            reservation = reservations_by_sku[item.sku_id]
            sku.reserved_quantity -= item.quantity
            reservation.quantity -= item.quantity
            if reservation.quantity == 0:
                to_delete.append(reservation)

        await self.reservation_repo.delete_many(to_delete)
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
        reservations = await self.reservation_repo.list_by_order(order_id)
        if not reservations:
            return
        await self.unreserve(
            UnreserveRequest(
                order_id=order_id,
                items=[
                    ReserveItem(sku_id=item.sku_id, quantity=item.quantity)
                    for item in reservations
                ],
            )
        )

    def _active_quantity(self, sku: object) -> int:
        return max(sku.stock - getattr(sku, "reserved_quantity", 0), 0)
