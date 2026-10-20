import asyncio
import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from src.core.config import settings
from src.core.database import get_db
from src.core.security import hash_password
from src.main import app
from src.models.carrier_webhook_receipt import CarrierWebhookReceipt
from src.models.local_carrier_label import LocalCarrierLabel
from src.models.seller import Seller
from src.models.seller_carrier_operation import SellerCarrierOperation
from src.models.seller_order import SellerOrder, SellerOrderItem
from src.models.seller_shipment import SellerShipment, SellerShipmentLine


@pytest.mark.postgres_integration
def test_live_signed_carrier_webhooks_reconcile_out_of_order_events() -> None:
    database_url = os.getenv("NEOMARKET_POSTGRES_TEST_URL")
    if not database_url:
        pytest.skip("set PostgreSQL URL for carrier webhook integration")

    async def scenario() -> None:
        engine = create_async_engine(database_url, poolclass=NullPool)
        sessions = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        seller_id, order_id, buyer_order_id, item_id, shipment_id, operation_id = (uuid4() for _ in range(6))
        dispatch_event_id, delivery_event_id = uuid4(), uuid4()
        now = datetime.now(timezone.utc)
        original_get_db = app.dependency_overrides.get(get_db)

        async def override_get_db():
            async with sessions() as session:
                yield session

        app.dependency_overrides[get_db] = override_get_db
        try:
            async with sessions() as session:
                seller = Seller(
                    id=seller_id,
                    email=f"seller-webhook-{uuid4()}@example.com",
                    hashed_password=hash_password("DisposableWebhook!2026"),
                    company_name="Webhook fixture",
                    is_active=True,
                    account_status="ACTIVE",
                    email_verified_at=now,
                )
                item = SellerOrderItem(
                    id=item_id,
                    sku_id=uuid4(),
                    product_id=uuid4(),
                    product_title="Webhook fixture",
                    sku_name="Single parcel",
                    quantity=1,
                    unit_price_minor=100,
                    line_total_minor=100,
                )
                order = SellerOrder(
                    id=order_id,
                    buyer_order_id=buyer_order_id,
                    seller_id=seller_id,
                    currency="RUB",
                    status="CREATED",
                    total_minor=100,
                    revision=2,
                    allocated_at=now,
                    seller_accepted_at=now,
                    items=[item],
                )
                shipment = SellerShipment(
                    id=shipment_id,
                    seller_order_id=order_id,
                    seller_id=seller_id,
                    idempotency_key=uuid4(),
                    request_sha256="a" * 64,
                    status="PACKED",
                    status_revision=0,
                    packed_at=now,
                    lines=[SellerShipmentLine(seller_order_item_id=item_id, quantity=1)],
                )
                operation = SellerCarrierOperation(
                    id=operation_id,
                    shipment_id=shipment_id,
                    seller_id=seller_id,
                    idempotency_key=uuid4(),
                    request_sha256="b" * 64,
                    provider="LOCAL_TEST",
                    provider_operation_ref=f"local-test:{shipment_id}",
                    status="LABEL_CREATED",
                    tracking_number=f"SIM-{uuid4().hex[:16].upper()}",
                    attempts=1,
                )
                label = LocalCarrierLabel(
                    shipment_id=shipment_id,
                    operation_ref=operation.provider_operation_ref,
                    tracking_number=operation.tracking_number,
                )
                session.add_all([seller, order, shipment])
                await session.flush()
                session.add_all([operation, label])
                await session.commit()

            def signed_request(client: TestClient, event: dict[str, object], *, signature_secret: str | None = None):
                body = json.dumps(event, separators=(",", ":"), sort_keys=True).encode()
                secret = signature_secret or settings.local_carrier_webhook_secret
                signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
                return client.post(
                    "/internal/v1/carriers/local-test/webhook",
                    content=body,
                    headers={"Content-Type": "application/json", "X-Local-Carrier-Signature": f"sha256={signature}"},
                )

            def make_event(event_id, event_type, revision):
                payload = {
                    "seller_order_id": str(order_id),
                    "shipment_id": str(shipment_id),
                    "provider_operation_ref": f"local-test:{shipment_id}",
                }
                return {
                    "schema_version": 1,
                    "event_id": str(event_id),
                    "event_type": event_type,
                    "producer": "LOCAL_TEST",
                    "aggregate_type": "shipment",
                    "aggregate_id": str(shipment_id),
                    "aggregate_revision": revision,
                    "tenant_id": str(seller_id),
                    "occurred_at": now.isoformat(),
                    "correlation_id": str(buyer_order_id),
                    "payload_hash": hashlib.sha256(
                        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
                    ).hexdigest(),
                    "payload": payload,
                }

            delivery_event = make_event(delivery_event_id, "shipment.delivered.v1", 2)
            dispatch_event = make_event(dispatch_event_id, "shipment.dispatched.v1", 1)
            client = TestClient(app)

            invalid_signature = client.post(
                "/internal/v1/carriers/local-test/webhook",
                json=dispatch_event,
                headers={"X-Local-Carrier-Signature": "sha256=" + "0" * 64},
            )
            assert invalid_signature.status_code == 401, invalid_signature.text

            early_delivery = signed_request(client, delivery_event)
            assert early_delivery.status_code == 202, early_delivery.text
            assert early_delivery.json()["status"] == "PENDING"
            assert early_delivery.json()["shipment_status"] == "PACKED"

            replay_pending = signed_request(client, delivery_event)
            assert replay_pending.status_code == 200, replay_pending.text
            assert replay_pending.json()["status"] == "PENDING"

            dispatch = signed_request(client, dispatch_event)
            assert dispatch.status_code == 202, dispatch.text
            assert dispatch.json()["shipment_status"] == "DELIVERED"

            replay_delivered = signed_request(client, delivery_event)
            assert replay_delivered.status_code == 200, replay_delivered.text
            assert replay_delivered.json()["status"] == "PROCESSED"
            assert replay_delivered.json()["shipment_status"] == "DELIVERED"

            changed_event = make_event(delivery_event_id, "shipment.delivered.v1", 2)
            changed_event["payload"]["provider_operation_ref"] = "local-test:changed"  # type: ignore[index]
            changed_event["payload_hash"] = hashlib.sha256(
                json.dumps(changed_event["payload"], sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            conflict = signed_request(client, changed_event)
            assert conflict.status_code == 409, conflict.text

            async with sessions() as session:
                shipment = await session.get(SellerShipment, shipment_id)
                assert shipment is not None and shipment.status == "DELIVERED" and shipment.status_revision == 2
                processed = await session.scalar(
                    select(func.count()).select_from(CarrierWebhookReceipt).where(
                        CarrierWebhookReceipt.shipment_id == shipment_id,
                        CarrierWebhookReceipt.status == "PROCESSED",
                    )
                )
                assert processed == 2
                pending = await session.scalar(
                    select(func.count()).select_from(CarrierWebhookReceipt).where(
                        CarrierWebhookReceipt.shipment_id == shipment_id,
                        CarrierWebhookReceipt.status == "PENDING",
                    )
                )
                assert pending == 0
        finally:
            if original_get_db is None:
                app.dependency_overrides.pop(get_db, None)
            else:
                app.dependency_overrides[get_db] = original_get_db
            async with sessions() as session:
                await session.execute(delete(CarrierWebhookReceipt).where(CarrierWebhookReceipt.shipment_id == shipment_id))
                await session.execute(delete(LocalCarrierLabel).where(LocalCarrierLabel.shipment_id == shipment_id))
                await session.execute(delete(SellerCarrierOperation).where(SellerCarrierOperation.shipment_id == shipment_id))
                await session.execute(delete(SellerShipmentLine).where(SellerShipmentLine.shipment_id == shipment_id))
                await session.execute(delete(SellerShipment).where(SellerShipment.id == shipment_id))
                order = await session.get(SellerOrder, order_id)
                if order is not None:
                    await session.delete(order)
                seller = await session.get(Seller, seller_id)
                if seller is not None:
                    await session.delete(seller)
                await session.commit()
            await engine.dispose()

    asyncio.run(scenario())
