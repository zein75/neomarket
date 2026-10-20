import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.inbox_event import InboxEvent
from src.models.seller import Seller
from src.models.seller_carrier_operation import SellerCarrierOperation
from src.models.seller_order import SellerOrder, SellerOrderItem
from src.models.seller_shipment import SellerShipment, SellerShipmentLine
from src.schemas.seller_order import (
    SellerOrderAllocationEvent,
    SellerOrderCancellationEvent,
    SellerPackingCreate,
)


class SellerOrderService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def receive_allocation(self, event: SellerOrderAllocationEvent) -> bool:
        payload_hash = hashlib.sha256(
            json.dumps(
                event.payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        if payload_hash != event.payload_hash:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "EVENT_HASH_MISMATCH", "message": "Allocation payload hash is invalid"},
            )

        seller_exists = await self.session.scalar(
            select(Seller.id).where(Seller.id == event.tenant_id)
        )
        if seller_exists is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "SELLER_NOT_FOUND", "message": "Seller not found"},
            )

        inserted = await self.session.execute(
            insert(InboxEvent)
            .values(
                id=uuid4(),
                producer=event.producer,
                event_id=event.event_id,
                payload_hash=payload_hash,
                status="RECEIVED",
                received_at=datetime.now(timezone.utc),
            )
            .on_conflict_do_nothing(index_elements=["producer", "event_id"])
        )
        if inserted.rowcount == 0:
            prior = await self.session.scalar(
                select(InboxEvent).where(
                    InboxEvent.producer == event.producer,
                    InboxEvent.event_id == event.event_id,
                )
            )
            if prior is None or prior.payload_hash != payload_hash:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"code": "EVENT_IDEMPOTENCY_CONFLICT", "message": "Event id was reused with a different payload"},
                )
            return False

        payload = event.payload
        order = SellerOrder(
            id=payload.seller_order_id,
            buyer_order_id=payload.buyer_order_id,
            seller_id=payload.seller_id,
            currency=payload.currency,
            status=payload.status,
            total_minor=payload.total_minor,
            revision=1,
            allocated_at=event.occurred_at,
            items=[
                SellerOrderItem(
                    sku_id=item.sku_id,
                    product_id=item.product_id,
                    product_title=item.product_title,
                    sku_name=item.sku_name,
                    quantity=item.quantity,
                    unit_price_minor=item.unit_price_minor,
                    line_total_minor=item.line_total_minor,
                )
                for item in payload.items
            ],
        )
        self.session.add(order)
        await self.session.flush()
        inbox = await self.session.scalar(
            select(InboxEvent).where(
                InboxEvent.producer == event.producer,
                InboxEvent.event_id == event.event_id,
            )
        )
        assert inbox is not None
        inbox.status = "PROCESSED"
        inbox.processed_at = datetime.now(timezone.utc)
        await self.session.flush()
        return True

    async def receive_cancellation(self, event: SellerOrderCancellationEvent) -> bool:
        payload_hash = hashlib.sha256(
            json.dumps(
                event.payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        if payload_hash != event.payload_hash:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "EVENT_HASH_MISMATCH", "message": "Cancellation payload hash is invalid"},
            )

        inserted = await self.session.execute(
            insert(InboxEvent)
            .values(
                id=uuid4(),
                producer=event.producer,
                event_id=event.event_id,
                payload_hash=payload_hash,
                status="RECEIVED",
                received_at=datetime.now(timezone.utc),
            )
            .on_conflict_do_nothing(index_elements=["producer", "event_id"])
        )
        if inserted.rowcount == 0:
            prior = await self.session.scalar(
                select(InboxEvent).where(
                    InboxEvent.producer == event.producer,
                    InboxEvent.event_id == event.event_id,
                )
            )
            if prior is None or prior.payload_hash != payload_hash:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"code": "EVENT_IDEMPOTENCY_CONFLICT", "message": "Event id was reused with a different payload"},
                )
            return False

        order = await self.session.scalar(
            select(SellerOrder)
            .where(
                SellerOrder.id == event.payload.seller_order_id,
                SellerOrder.buyer_order_id == event.payload.buyer_order_id,
                SellerOrder.seller_id == event.payload.seller_id,
            )
            .with_for_update()
        )
        if order is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "SELLER_ORDER_NOT_FOUND", "message": "Seller order not found"},
            )
        if order.status != "CANCELLED":
            order.status = "CANCELLED"
            order.revision += 1
        inbox = await self.session.scalar(
            select(InboxEvent).where(
                InboxEvent.producer == event.producer,
                InboxEvent.event_id == event.event_id,
            )
        )
        assert inbox is not None
        inbox.status = "PROCESSED"
        inbox.processed_at = datetime.now(timezone.utc)
        await self.session.flush()
        return True

    async def list_for_seller(self, seller_id, *, limit: int, cursor=None) -> list[SellerOrder]:
        query = (
            select(SellerOrder)
            .options(selectinload(SellerOrder.items))
            .where(SellerOrder.seller_id == seller_id)
            .order_by(SellerOrder.allocated_at.desc(), SellerOrder.id.desc())
        )
        if cursor is not None:
            allocated_at, order_id = cursor
            query = query.where(
                or_(
                    SellerOrder.allocated_at < allocated_at,
                    and_(SellerOrder.allocated_at == allocated_at, SellerOrder.id < order_id),
                )
            )
        result = await self.session.execute(query.limit(limit + 1))
        return list(result.scalars().all())

    async def get_for_seller(self, seller_id, seller_order_id) -> SellerOrder | None:
        result = await self.session.execute(
            select(SellerOrder)
            .options(
                selectinload(SellerOrder.items),
                selectinload(SellerOrder.shipments).selectinload(SellerShipment.lines),
                selectinload(SellerOrder.shipments).selectinload(SellerShipment.carrier_operation),
            )
            .where(SellerOrder.id == seller_order_id, SellerOrder.seller_id == seller_id)
        )
        return result.scalar_one_or_none()

    async def create_packed_shipment(
        self,
        seller_id,
        seller_order_id,
        *,
        idempotency_key,
        request: SellerPackingCreate,
    ) -> tuple[SellerShipment | None, bool]:
        canonical_lines = sorted(
            (
                {"seller_order_item_id": str(line.seller_order_item_id), "quantity": line.quantity}
                for line in request.lines
            ),
            key=lambda line: line["seller_order_item_id"],
        )
        request_hash = hashlib.sha256(
            json.dumps(canonical_lines, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        result = await self.session.execute(
            select(SellerOrder)
            .options(
                selectinload(SellerOrder.items),
                selectinload(SellerOrder.shipments).selectinload(SellerShipment.lines),
                selectinload(SellerOrder.shipments).selectinload(SellerShipment.carrier_operation),
            )
            .where(SellerOrder.id == seller_order_id, SellerOrder.seller_id == seller_id)
            .with_for_update()
        )
        order = result.scalar_one_or_none()
        if order is None:
            return None, False

        previous = next(
            (shipment for shipment in order.shipments if shipment.idempotency_key == idempotency_key),
            None,
        )
        if previous is not None:
            if previous.request_sha256 != request_hash:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"code": "IDEMPOTENCY_CONFLICT", "message": "Idempotency key was used with a different packing manifest"},
                )
            return previous, False

        if order.seller_accepted_at is None or order.status != "CREATED":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "ALLOCATION_NOT_PACKABLE", "message": "Allocation is not available for packing"},
            )

        items_by_id = {item.id: item for item in order.items}
        already_packed: dict[UUID, int] = {}
        for shipment in order.shipments:
            for line in shipment.lines:
                already_packed[line.seller_order_item_id] = (
                    already_packed.get(line.seller_order_item_id, 0) + line.quantity
                )
        for line in request.lines:
            item = items_by_id.get(line.seller_order_item_id)
            if item is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"code": "ORDER_LINE_NOT_FOUND", "message": "Packing line is not part of this allocation"},
                )
            remaining = item.quantity - already_packed.get(item.id, 0)
            if line.quantity > remaining:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"code": "PACKING_QUANTITY_EXCEEDS_REMAINING", "message": "Packed quantity exceeds the unshipped allocation"},
                )

        shipment = SellerShipment(
            seller_order_id=order.id,
            seller_id=order.seller_id,
            idempotency_key=idempotency_key,
            request_sha256=request_hash,
            status="PACKED",
            packed_at=datetime.now(timezone.utc),
            lines=[
                SellerShipmentLine(seller_order_item_id=line.seller_order_item_id, quantity=line.quantity)
                for line in request.lines
            ],
            carrier_operation=None,
        )
        order.revision += 1
        self.session.add(shipment)
        await self.session.flush()
        return shipment, True

    async def accept_allocation(self, seller_id, seller_order_id) -> SellerOrder | None:
        result = await self.session.execute(
            select(SellerOrder)
            .options(selectinload(SellerOrder.items))
            .where(SellerOrder.id == seller_order_id, SellerOrder.seller_id == seller_id)
            .with_for_update()
        )
        order = result.scalar_one_or_none()
        if order is None:
            return None
        if order.seller_accepted_at is not None:
            return order
        if order.status != "CREATED":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "ALLOCATION_NOT_ACCEPTABLE", "message": "Allocation cannot be accepted in its current state"},
            )
        order.seller_accepted_at = datetime.now(timezone.utc)
        order.revision += 1
        await self.session.flush()
        return order

    async def prepare_carrier_operation(
        self, seller_id, seller_order_id, shipment_id, *, idempotency_key
    ) -> tuple[SellerCarrierOperation | None, SellerShipment | None, bool]:
        result = await self.session.execute(
            select(SellerShipment)
            .join(SellerOrder, SellerOrder.id == SellerShipment.seller_order_id)
            .options(
                selectinload(SellerShipment.lines),
                selectinload(SellerShipment.carrier_operation),
                selectinload(SellerShipment.seller_order),
            )
            .where(
                SellerOrder.id == seller_order_id,
                SellerOrder.seller_id == seller_id,
                SellerShipment.id == shipment_id,
                SellerShipment.seller_id == seller_id,
            )
            .with_for_update(of=SellerShipment)
        )
        shipment = result.scalar_one_or_none()
        if shipment is None:
            return None, None, False
        if (
            shipment.seller_order.seller_accepted_at is None
            or shipment.seller_order.status != "CREATED"
            or shipment.status != "PACKED"
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "SHIPMENT_NOT_DISPATCHABLE", "message": "Only an accepted packed parcel can be submitted"},
            )

        operation = shipment.carrier_operation
        if operation is not None:
            if operation.idempotency_key != idempotency_key:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"code": "CARRIER_OPERATION_CONFLICT", "message": "A carrier operation already exists for this parcel"},
                )
            return operation, shipment, False

        operation = SellerCarrierOperation(
            shipment_id=shipment.id,
            seller_id=seller_id,
            idempotency_key=idempotency_key,
            request_sha256=hashlib.sha256(str(shipment.id).encode()).hexdigest(),
            provider="LOCAL_TEST",
            provider_operation_ref=f"local-test:{shipment.id}",
            status="PENDING_PROVIDER",
            attempts=0,
        )
        shipment.carrier_operation = operation
        self.session.add(operation)
        await self.session.flush()
        return operation, shipment, True

    async def get_carrier_operation(self, seller_id, seller_order_id, shipment_id):
        result = await self.session.execute(
            select(SellerCarrierOperation)
            .join(SellerShipment, SellerShipment.id == SellerCarrierOperation.shipment_id)
            .where(
                SellerCarrierOperation.shipment_id == shipment_id,
                SellerCarrierOperation.seller_id == seller_id,
                SellerShipment.seller_order_id == seller_order_id,
                SellerShipment.seller_id == seller_id,
            )
        )
        return result.scalar_one_or_none()
