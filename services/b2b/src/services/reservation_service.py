import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.clients.b2c import B2CClient
from src.clients.moderation import ModerationClient
from src.models.product import ProductStatus
from src.models.inventory_order_lifecycle import InventoryOrderLifecycle, ReservationLine
from src.models.inventory_ledger import InventoryLedger
from src.repositories.fulfilled_order_repo import FulfilledOrderRepository
from src.repositories.reservation_operation_repo import ReservationOperationRepository
from src.repositories.reservation_repo import ReservationRepository
from src.repositories.outbox_event_repo import OutboxEventRepository
from src.repositories.unreserve_operation_repo import UnreserveOperationRepository
from src.repositories.sku_repo import SKURepository
from src.schemas.reservation import (
    FulfillRequest,
    ReserveRequest,
    ReserveItem,
    UnreserveRequest,
)


class ReservationService:
    MAX_OUTBOX_ATTEMPTS = 12
    def __init__(self, session: AsyncSession) -> None:
        self.reservation_repo = ReservationRepository(session)
        self.reservation_operation_repo = ReservationOperationRepository(session)
        self.sku_repo = SKURepository(session)
        self.fulfilled_order_repo = FulfilledOrderRepository(session)
        self.outbox_repo = OutboxEventRepository(session)
        self.unreserve_operation_repo = UnreserveOperationRepository(session)

    async def reserve(self, data: ReserveRequest) -> dict[str, object]:
        idempotency_key = str(data.idempotency_key)
        request_hash = self._reserve_request_hash(data)
        existing = await self.reservation_operation_repo.get_by_idempotency_key(
            idempotency_key
        )
        if existing:
            if not getattr(existing, "is_expired", lambda: False)():
                return await self._existing_reservation_result(existing, request_hash)
            await self.reservation_operation_repo.session.delete(existing)
            await self.reservation_operation_repo.session.flush()

        lifecycle = await self._load_lifecycle(data.order_id, for_update=True)
        if lifecycle is not None and lifecycle.state != "NEW":
            # A concurrent retry can observe the durable RESERVED lifecycle
            # after the first transaction committed, while its operation row
            # is not yet visible in the current session snapshot.  Replay the
            # exact original response for the same request instead of
            # misclassifying the idempotent retry as a terminal order.
            if (
                lifecycle.state == "RESERVED"
                and lifecycle.fingerprint == request_hash
                and lifecycle.result
            ):
                return self._decode_reservation_response(lifecycle.result)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "ORDER_TERMINAL", "message": "Inventory order is already finalized"},
            )

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

        for sku in skus:
            self._assert_inventory_consistent(sku)

        # Re-check after the SKU locks: a concurrent retry may have completed
        # the same idempotent operation while this request was waiting.
        existing = await self.reservation_operation_repo.get_by_idempotency_key(
            idempotency_key
        )
        if existing:
            if not getattr(existing, "is_expired", lambda: False)():
                return await self._existing_reservation_result(existing, request_hash)
            await self.reservation_operation_repo.session.delete(existing)
            await self.reservation_operation_repo.session.flush()

        failed_items = []
        for item in data.items:
            sku = skus_by_id[item.sku_id]
            product = getattr(sku, "product", None)
            product_status = getattr(product, "status", None)
            available = self._active_quantity(sku)
            reason = self._reservation_failure_reason(
                sku=sku,
                product=product,
                product_status=product_status,
                available=available,
                requested=item.quantity,
            )
            if reason is not None:
                failed_items.append(
                    {
                        "sku_id": str(item.sku_id),
                        "requested": item.quantity,
                        "available": available,
                        "reason": reason,
                    }
                )

        if failed_items:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "INSUFFICIENT_STOCK",
                    "message": "Insufficient stock",
                    # The public Error schema keeps endpoint-specific data
                    # inside ``details``; do not leak ReserveResponse fields
                    # into a 409 payload.
                    "details": {"failed_items": failed_items},
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
            reserved_at = datetime.now(timezone.utc)
            response = {
                "status": "RESERVED",
                "order_id": str(data.order_id),
                "reserved_at": reserved_at.isoformat(),
                "reserved": True,
                "items": [
                    {
                        "sku_id": str(item["sku_id"]),
                        "reserved_quantity": item["reserved_quantity"],
                        "remaining_stock": item["remaining_stock"],
                    }
                    for item in response_items
                ],
            }
            self._record_reserved_lifecycle(
                order_id=data.order_id,
                request_hash=request_hash,
                items=data.items,
                response=response,
                reserved_at=reserved_at,
            )
            # Persist the exact first response in the same transaction as the
            # inventory mutation. Retries must not derive remaining_stock from
            # the current SKU state.
            await self.reservation_operation_repo.create(
                idempotency_key=idempotency_key,
                order_id=data.order_id,
                request_hash=request_hash,
                response=response,
            )
            outbox_events = []
            for sku in out_of_stock_skus:
                event = {
                    "event": "SKU_OUT_OF_STOCK",
                    # The outbox row is the delivery identity. A fresh UUID
                    # also keeps a legitimate key reuse after the one-hour
                    # reserve-operation TTL from colliding with an old event.
                    "idempotency_key": str(uuid4()),
                    "date": datetime.now(timezone.utc).isoformat(),
                    "product_id": str(sku.product_id),
                    "sku_ids": [str(sku.id)],
                }
                outbox_event = await self.outbox_repo.create_b2c_event(
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
                if outbox_event is not None:
                    outbox_events.append(outbox_event)
        except IntegrityError:
            rollback = getattr(self.reservation_operation_repo.session, "rollback", None)
            if rollback:
                await rollback()
            existing = await self.reservation_operation_repo.get_by_idempotency_key(
                idempotency_key
            )
            if not existing:
                raise
            return await self._existing_reservation_result(existing, request_hash)
        if not outbox_events:
            # Test doubles without persistence still exercise the notification path.
            # With a real DB the outbox worker delivers only after the request
            # transaction commits, avoiding notifications for rolled-back work.
            for sku in out_of_stock_skus:
                try:
                    await B2CClient().send_sku_out_of_stock(sku)
                except Exception:  # noqa: BLE001 - keep the event pending for retry
                    pass
        return self._decode_reservation_response(response)

    def _record_reserved_lifecycle(
        self,
        *,
        order_id: UUID,
        request_hash: str,
        items: list[ReserveItem],
        response: dict[str, object],
        reserved_at: datetime,
    ) -> None:
        """Write the durable inventory state in the same DB transaction.

        Lightweight test doubles do not expose ``add``; the existing
        reservation tables remain the compatibility path for those tests.
        Real SQLAlchemy sessions always provide ``add``.
        """
        add = getattr(self.reservation_repo.session, "add", None)
        if add is None:
            return
        add(
            InventoryOrderLifecycle(
                order_id=order_id,
                fingerprint=request_hash,
                state="RESERVED",
                version=1,
                reserved_at=reserved_at,
                source="b2c-order",
                result=response,
            )
        )
        for item in items:
            add(
                ReservationLine(
                    order_id=order_id,
                    sku_id=item.sku_id,
                    quantity=item.quantity,
                    state="ACTIVE",
                )
            )

    async def _existing_reservation_result(
        self, operation: object, request_hash: str
    ) -> dict[str, object]:
        """Return a replay only for the exact request that created the key."""
        if getattr(operation, "request_hash", None) != request_hash:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "IDEMPOTENCY_CONFLICT",
                    "message": "idempotency_key used with different payload",
                },
            )
        # The first response belongs to the key. Reusing a key after a later
        # reservation must never recalculate remaining stock.
        return await self._reservation_result(operation)

    @staticmethod
    def _reserve_request_hash(data: ReserveRequest) -> str:
        payload = {
            "order_id": str(data.order_id),
            # Request-item ordering has no inventory meaning, so canonicalise
            # it before hashing to preserve legitimate retries.
            "items": sorted(
                ({"sku_id": str(item.sku_id), "quantity": item.quantity} for item in data.items),
                key=lambda item: item["sku_id"],
            ),
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    async def _reservation_result(self, operation: object) -> dict[str, object]:
        stored_response = getattr(operation, "response", None)
        if stored_response:
            return self._decode_reservation_response(stored_response)
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

    @staticmethod
    def _decode_reservation_response(response: dict[str, object]) -> dict[str, object]:
        decoded = dict(response)
        decoded["order_id"] = UUID(str(decoded["order_id"]))
        decoded["reserved_at"] = datetime.fromisoformat(str(decoded["reserved_at"]))
        decoded["items"] = [
            {**item, "sku_id": UUID(str(item["sku_id"]))}
            for item in decoded.get("items", [])
        ]
        return decoded

    @staticmethod
    def _encode_unreserve_response(response: dict[str, object]) -> dict[str, object]:
        return {
            **response,
            "order_id": str(response["order_id"]),
            "processed_at": response["processed_at"].isoformat(),
        }

    @staticmethod
    def _decode_unreserve_response(response: dict[str, object]) -> dict[str, object]:
        return {
            **response,
            "order_id": UUID(str(response["order_id"])),
            "processed_at": datetime.fromisoformat(str(response["processed_at"])),
        }

    async def retry_pending_outbox(self, limit: int = 100) -> int:
        delivered = 0
        claim = getattr(self.outbox_repo, "claim_pending", None)
        if claim is not None:
            events = await claim(worker_id="b2b-outbox", limit=limit)
        else:
            events = await self.outbox_repo.list_pending(limit)
        for event in events:
            event.attempts += 1
            if event.attempts > self.MAX_OUTBOX_ATTEMPTS:
                event.status = "DEAD"
                event.last_error = "OUTBOX_MAX_ATTEMPTS_EXCEEDED"
                event.lease_owner = None
                event.lease_until = None
                continue
            if getattr(event, "payload_sha256", None):
                actual_hash = hashlib.sha256(
                    json.dumps(
                        event.payload, sort_keys=True, separators=(",", ":")
                    ).encode()
                ).hexdigest()
                if actual_hash != event.payload_sha256:
                    event.status = "DEAD"
                    event.last_error = "OUTBOX_PAYLOAD_HASH_MISMATCH"
                    event.lease_owner = None
                    event.lease_until = None
                    continue
            try:
                if event.destination == "B2C":
                    await B2CClient().send_outbox_event(event.payload)
                elif event.destination == "MODERATION":
                    await ModerationClient()._post_event(event.payload)
                else:
                    event.status = "DEAD"
                    event.last_error = "OUTBOX_UNKNOWN_DESTINATION"
                    event.lease_owner = None
                    event.lease_until = None
                    continue
                event.status = "SENT"
                event.lease_owner = None
                event.lease_until = None
                event.last_error = None
                delivered += 1
            except Exception as exc:  # noqa: BLE001 - keep the event pending for recovery
                # Keep the first failure immediately retryable for backwards
                # compatibility; subsequent failures enter exponential backoff.
                event.status = "PENDING" if event.attempts == 1 else "RETRY"
                event.lease_owner = None
                event.lease_until = None
                event.last_error = str(exc)[:500]
                event.next_retry_at = (
                    None
                    if event.attempts == 1
                    else datetime.now(timezone.utc)
                    + timedelta(seconds=min(900, 2 ** min(event.attempts, 10)))
                )
                continue
        await self.outbox_repo.session.flush()
        return delivered

    async def unreserve(self, data: UnreserveRequest) -> dict[str, object]:
        request_payload = {
            "order_id": str(data.order_id),
            "items": [
                {"sku_id": str(item.sku_id), "quantity": item.quantity}
                for item in data.items
            ],
        }
        request_hash = hashlib.sha256(
            json.dumps(request_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        existing_operation = await self.unreserve_operation_repo.get_by_order_id(
            data.order_id
        )
        if existing_operation:
            if existing_operation.request_hash != request_hash:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "code": "IDEMPOTENCY_CONFLICT",
                        "message": "order_id used with different payload",
                    },
                )
            return self._decode_unreserve_response(existing_operation.response)

        lifecycle = await self._load_lifecycle(data.order_id, for_update=True)
        if lifecycle is not None and lifecycle.state == "FULFILLED":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "ORDER_TERMINAL", "message": "Fulfilled order cannot be unreserved"},
            )

        sku_ids = [item.sku_id for item in data.items]
        if len(set(sku_ids)) != len(sku_ids):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "INVALID_REQUEST",
                    "message": "Duplicate SKU in unreserve",
                },
            )

        reservations = await self.reservation_repo.list_by_order(data.order_id)
        if not reservations:
            response = {
                "status": "UNRESERVED",
                "order_id": data.order_id,
                "processed_at": datetime.now(timezone.utc),
            }
            await self.unreserve_operation_repo.create(
                order_id=data.order_id,
                request_hash=request_hash,
                request_payload=request_payload,
                response=self._encode_unreserve_response(response),
            )
            await self._mark_lifecycle_cancelled(
                data.order_id,
                request_hash,
                self._encode_unreserve_response(response),
            )
            return response
        skus = await self.sku_repo.list_for_update(sku_ids)
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
            if sku.reserved_quantity < item.quantity:
                raise self._inventory_corruption()

        response = {
            "status": "UNRESERVED",
            "order_id": data.order_id,
            "processed_at": datetime.now(timezone.utc),
        }
        try:
            await self.unreserve_operation_repo.create(
                order_id=data.order_id,
                request_hash=request_hash,
                request_payload=request_payload,
                response=self._encode_unreserve_response(response),
            )
        except IntegrityError:
            await self.unreserve_operation_repo.session.rollback()
            existing_operation = await self.unreserve_operation_repo.get_by_order_id(
                data.order_id
            )
            if existing_operation is None:
                raise
            if existing_operation.request_hash != request_hash:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "code": "IDEMPOTENCY_CONFLICT",
                        "message": "order_id used with different payload",
                    },
                )
            return self._decode_unreserve_response(existing_operation.response)

        to_delete = []
        for item in data.items:
            sku = skus_by_id[item.sku_id]
            reservation = reservations_by_sku[item.sku_id]
            sku.reserved_quantity -= item.quantity
            reservation.quantity -= item.quantity
            if reservation.quantity == 0:
                to_delete.append(reservation)
                await self._mark_line_state(data.order_id, item.sku_id, "RELEASED")

            await self._record_reserved_delta(
                order_id=data.order_id,
                sku_id=item.sku_id,
                delta_reserved=-item.quantity,
                reason="UNRESERVE",
            )

        await self.reservation_repo.delete_many(to_delete)
        if len(to_delete) == len(reservations):
            await self._mark_lifecycle_cancelled(
                data.order_id,
                request_hash,
                self._encode_unreserve_response(response),
            )
        await self.reservation_repo.session.flush()
        return response

    async def fulfill(self, data: FulfillRequest) -> dict[str, object]:
        if await self.fulfilled_order_repo.exists(data.order_id):
            return {
                "status": "FULFILLED",
                "order_id": data.order_id,
                "processed_at": datetime.now(timezone.utc),
            }

        lifecycle = await self._load_lifecycle(data.order_id, for_update=True)
        if lifecycle is not None and lifecycle.state == "CANCELLED":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "ORDER_TERMINAL", "message": "Cancelled order cannot be fulfilled"},
            )
        if lifecycle is not None and lifecycle.state == "FULFILLED":
            return {
                "status": "FULFILLED",
                "order_id": data.order_id,
                "processed_at": lifecycle.terminal_at or datetime.now(timezone.utc),
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
            if sku is None:
                raise self._inventory_corruption()
            self._assert_inventory_consistent(sku)
            if (
                sku.stock < reservation.quantity
                or sku.reserved_quantity < reservation.quantity
            ):
                raise self._inventory_corruption()
            sku.stock -= reservation.quantity
            if getattr(sku, "on_hand", None) is not None:
                sku.on_hand -= reservation.quantity
            sku.reserved_quantity -= reservation.quantity
            await self._record_reserved_delta(
                order_id=data.order_id,
                sku_id=reservation.sku_id,
                delta_on_hand=-reservation.quantity,
                delta_reserved=-reservation.quantity,
                reason="FULFILL",
            )
            await self._mark_line_state(
                data.order_id, reservation.sku_id, "FULFILLED"
            )
        await self.reservation_repo.delete_many(reservations)
        await self.fulfilled_order_repo.mark_fulfilled(data.order_id)
        await self._mark_lifecycle_fulfilled(data.order_id)
        await self.reservation_repo.session.flush()
        return {
            "status": "FULFILLED",
            "order_id": data.order_id,
            "processed_at": datetime.now(timezone.utc),
        }

    def _active_quantity(self, sku: object) -> int:
        on_hand = getattr(sku, "on_hand", None)
        base = sku.stock if on_hand is None else on_hand
        return base - getattr(sku, "reserved_quantity", 0)

    @staticmethod
    def _assert_inventory_consistent(sku: object) -> None:
        stock = int(getattr(sku, "stock", 0))
        reserved = int(getattr(sku, "reserved_quantity", 0))
        if stock < 0 or reserved < 0 or reserved > stock:
            raise ReservationService._inventory_corruption()

    @staticmethod
    def _inventory_corruption() -> HTTPException:
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "INVENTORY_CORRUPTION",
                "message": "Inventory state is inconsistent",
            },
        )

    async def _load_lifecycle(
        self, order_id: UUID, *, for_update: bool = False
    ) -> InventoryOrderLifecycle | None:
        execute = getattr(self.reservation_repo.session, "execute", None)
        if execute is None:
            return None
        query = select(InventoryOrderLifecycle).where(
            InventoryOrderLifecycle.order_id == order_id
        )
        if for_update:
            query = query.with_for_update()
        result = await execute(query)
        return result.scalar_one_or_none()

    async def _mark_lifecycle_cancelled(
        self,
        order_id: UUID,
        request_hash: str,
        response: dict[str, object],
    ) -> None:
        lifecycle = await self._load_lifecycle(order_id)
        if lifecycle is None:
            add = getattr(self.reservation_repo.session, "add", None)
            if add is None:
                return
            add(
                InventoryOrderLifecycle(
                    order_id=order_id,
                    fingerprint=request_hash,
                    state="CANCELLED",
                    version=1,
                    terminal_at=datetime.now(timezone.utc),
                    source="b2c-order",
                    result=response,
                )
            )
            return
        lifecycle.state = "CANCELLED"
        lifecycle.version += 1
        lifecycle.terminal_at = datetime.now(timezone.utc)
        lifecycle.result = response

    async def _mark_lifecycle_fulfilled(self, order_id: UUID) -> None:
        lifecycle = await self._load_lifecycle(order_id)
        if lifecycle is None:
            return
        lifecycle.state = "FULFILLED"
        lifecycle.version += 1
        lifecycle.terminal_at = datetime.now(timezone.utc)

    async def _mark_line_state(self, order_id: UUID, sku_id: UUID, state: str) -> None:
        execute = getattr(self.reservation_repo.session, "execute", None)
        if execute is None:
            return
        result = await execute(
            select(ReservationLine).where(
                ReservationLine.order_id == order_id,
                ReservationLine.sku_id == sku_id,
            )
        )
        line = result.scalar_one_or_none()
        if line is not None:
            line.state = state

    async def _record_reserved_delta(
        self,
        *,
        order_id: UUID,
        sku_id: UUID,
        reason: str,
        delta_reserved: int = 0,
        delta_on_hand: int = 0,
    ) -> None:
        add = getattr(self.reservation_repo.session, "add", None)
        if add is None:
            return
        add(
            InventoryLedger(
                event_id=uuid4(),
                order_id=order_id,
                sku_id=sku_id,
                delta_on_hand=delta_on_hand,
                delta_reserved=delta_reserved,
                reason=reason,
                actor_type="b2c-order",
                occurred_at=datetime.now(timezone.utc),
                correlation_id=str(order_id),
            )
        )

    def _reservation_failure_reason(
        self,
        *,
        sku: object,
        product: object | None,
        product_status: object,
        available: int,
        requested: int,
    ) -> str | None:
        if not getattr(sku, "is_active", True) or getattr(sku, "deleted", False):
            return "SKU_NOT_FOUND"
        if getattr(product, "deleted", False):
            return "PRODUCT_DELETED"
        if product_status != ProductStatus.MODERATED:
            return "PRODUCT_BLOCKED"
        if available < requested:
            return "OUT_OF_STOCK" if available == 0 else "INSUFFICIENT_STOCK"
        return None
