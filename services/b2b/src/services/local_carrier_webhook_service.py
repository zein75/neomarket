import hashlib
import json
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.carrier_webhook_receipt import CarrierWebhookReceipt
from src.models.seller_carrier_operation import SellerCarrierOperation
from src.models.seller_order import SellerOrder
from src.models.seller_shipment import SellerShipment
from src.schemas.seller_order import CarrierWebhookResponse, LocalCarrierWebhookEvent


class LocalCarrierWebhookService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def receive(self, event: LocalCarrierWebhookEvent) -> tuple[CarrierWebhookResponse, bool]:
        payload_hash = hashlib.sha256(
            json.dumps(event.payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if payload_hash != event.payload_hash:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "EVENT_HASH_MISMATCH", "message": "Carrier event payload hash is invalid"},
            )

        shipment = await self.session.scalar(
            select(SellerShipment)
            .join(SellerOrder, SellerOrder.id == SellerShipment.seller_order_id)
            .where(
                SellerShipment.id == event.payload.shipment_id,
                SellerOrder.id == event.payload.seller_order_id,
                SellerOrder.seller_id == event.tenant_id,
                SellerShipment.seller_id == event.tenant_id,
            )
            .with_for_update(of=SellerShipment)
        )
        if shipment is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "SELLER_SHIPMENT_NOT_FOUND", "message": "Shipment not found"},
            )
        operation = await self.session.scalar(
            select(SellerCarrierOperation).where(SellerCarrierOperation.shipment_id == shipment.id)
        )
        if (
            operation is None
            or operation.provider != "LOCAL_TEST"
            or operation.provider_operation_ref != event.payload.provider_operation_ref
            or operation.status != "LABEL_CREATED"
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "CARRIER_OPERATION_NOT_READY", "message": "A local label is required before carrier events"},
            )

        prior = await self.session.get(CarrierWebhookReceipt, event.event_id)
        if prior is not None:
            if prior.payload_sha256 != payload_hash or prior.shipment_id != shipment.id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"code": "EVENT_IDEMPOTENCY_CONFLICT", "message": "Carrier event id was reused"},
                )
            return CarrierWebhookResponse(
                event_id=prior.event_id,
                status=prior.status,
                shipment_status=shipment.status,
            ), False

        revision_event = await self.session.scalar(
            select(CarrierWebhookReceipt).where(
                CarrierWebhookReceipt.shipment_id == shipment.id,
                CarrierWebhookReceipt.aggregate_revision == event.aggregate_revision,
            )
        )
        if revision_event is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "CARRIER_REVISION_CONFLICT", "message": "Shipment revision already has a different event"},
            )

        receipt = CarrierWebhookReceipt(
            event_id=event.event_id,
            shipment_id=shipment.id,
            aggregate_revision=event.aggregate_revision,
            event_type=event.event_type,
            payload_sha256=payload_hash,
            payload=event.payload.model_dump(mode="json"),
            status="PENDING",
            occurred_at=event.occurred_at,
            received_at=datetime.now(timezone.utc),
        )
        self.session.add(receipt)
        await self.session.flush()

        while True:
            next_event = await self.session.scalar(
                select(CarrierWebhookReceipt).where(
                    CarrierWebhookReceipt.shipment_id == shipment.id,
                    CarrierWebhookReceipt.aggregate_revision == shipment.status_revision + 1,
                    CarrierWebhookReceipt.status == "PENDING",
                )
            )
            if next_event is None:
                break
            expected_status = "PACKED" if next_event.aggregate_revision == 1 else "DISPATCHED"
            if shipment.status != expected_status:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"code": "CARRIER_TRANSITION_CONFLICT", "message": "Carrier event cannot advance shipment state"},
                )
            shipment.status = "DISPATCHED" if next_event.aggregate_revision == 1 else "DELIVERED"
            shipment.status_revision = next_event.aggregate_revision
            next_event.status = "PROCESSED"
            next_event.processed_at = datetime.now(timezone.utc)

        return CarrierWebhookResponse(
            event_id=receipt.event_id,
            status=receipt.status,
            shipment_status=shipment.status,
        ), True
