import asyncio
import hashlib
import json
import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from src.api.deps import verify_service_key
from src.core.database import get_db
from src.core.security import hash_password
from src.main import app
from src.models.inbox_event import InboxEvent
from src.models.seller import Seller
from src.models.seller_order import SellerOrder, SellerOrderItem
from src.models.seller_shipment import SellerShipment, SellerShipmentLine
from src.services.seller_order_service import SellerOrderService
from src.schemas.seller_order import SellerPackingCreate


@pytest.mark.postgres_integration
def test_live_cancellation_event_blocks_new_packing_and_is_idempotent() -> None:
    database_url = os.getenv("NEOMARKET_POSTGRES_TEST_URL")
    if not database_url:
        pytest.skip("set PostgreSQL URL for seller order cancellation integration")

    async def scenario() -> None:
        engine = create_async_engine(database_url, poolclass=NullPool)
        sessions = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        seller_id, buyer_order_id, order_id, item_id, shipment_id, event_id = (uuid4() for _ in range(6))
        now = datetime.now(timezone.utc)
        try:
            async with sessions() as session:
                seller = Seller(
                    id=seller_id,
                    email=f"seller-cancel-{uuid4()}@example.com",
                    hashed_password=hash_password("DisposableCancel!2026"),
                    company_name="Cancellation fixture",
                    is_active=True,
                    account_status="ACTIVE",
                    email_verified_at=now,
                )
                item = SellerOrderItem(
                    id=item_id,
                    sku_id=uuid4(),
                    product_id=uuid4(),
                    product_title="Cancellation fixture",
                    sku_name="One parcel",
                    quantity=2,
                    unit_price_minor=250,
                    line_total_minor=500,
                )
                order = SellerOrder(
                    id=order_id,
                    buyer_order_id=buyer_order_id,
                    seller_id=seller_id,
                    currency="RUB",
                    status="CREATED",
                    total_minor=500,
                    revision=1,
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
                    packed_at=now,
                    lines=[SellerShipmentLine(seller_order_item_id=item_id, quantity=1)],
                )
                session.add_all([seller, order, shipment])
                await session.commit()

            inner_payload = {
                "buyer_order_id": str(buyer_order_id),
                "seller_order_id": str(order_id),
                "seller_id": str(seller_id),
            }
            event = {
                "schema_version": 1,
                "event_id": str(event_id),
                "event_type": "seller_order.cancelled.v1",
                "producer": "b2c",
                "aggregate_type": "seller_order",
                "aggregate_id": str(order_id),
                "aggregate_version": 2,
                "tenant_id": str(seller_id),
                "occurred_at": now.isoformat(),
                "correlation_id": str(buyer_order_id),
                "payload_hash": hashlib.sha256(
                    json.dumps(inner_payload, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest(),
                "payload": inner_payload,
            }
            original_get_db = app.dependency_overrides.get(get_db)
            original_verify = app.dependency_overrides.get(verify_service_key)

            async def override_get_db():
                async with sessions() as session:
                    yield session

            app.dependency_overrides[get_db] = override_get_db
            app.dependency_overrides[verify_service_key] = lambda: None
            try:
                client = TestClient(app)
                path = "/internal/v1/seller-orders/cancellations"
                accepted = client.post(path, json=event)
                assert accepted.status_code == 202, accepted.text
                replay = client.post(path, json=event)
                assert replay.status_code == 200, replay.text
            finally:
                if original_get_db is None:
                    app.dependency_overrides.pop(get_db, None)
                else:
                    app.dependency_overrides[get_db] = original_get_db
                if original_verify is None:
                    app.dependency_overrides.pop(verify_service_key, None)
                else:
                    app.dependency_overrides[verify_service_key] = original_verify

            async with sessions() as session:
                persisted = await session.get(SellerOrder, order_id)
                assert persisted is not None and persisted.status == "CANCELLED"
                assert persisted.revision == 2
                received = await session.scalar(
                    select(InboxEvent).where(InboxEvent.producer == "b2c", InboxEvent.event_id == event_id)
                )
                assert received is not None and received.status == "PROCESSED"
                with pytest.raises(HTTPException) as error:
                    await SellerOrderService(session).create_packed_shipment(
                        seller_id,
                        order_id,
                        idempotency_key=uuid4(),
                        request=SellerPackingCreate(lines=[{"seller_order_item_id": item_id, "quantity": 1}]),
                    )
                assert getattr(error.value, "status_code", None) == 409
        finally:
            async with sessions() as session:
                await session.execute(delete(InboxEvent).where(InboxEvent.event_id == event_id))
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
