import asyncio
import hashlib
import json
import os
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from src.models.order import SellerOrderOutbox
from src.services.order_service import OrderService


@pytest.mark.postgres_integration
def test_live_seller_cancellation_outbox_persists_beside_allocation_event() -> None:
    database_url = os.getenv("NEOMARKET_POSTGRES_TEST_URL")
    if not database_url:
        pytest.skip("set PostgreSQL URL for seller cancellation outbox integration")

    async def scenario() -> None:
        engine = create_async_engine(database_url, poolclass=NullPool)
        sessions = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        buyer_order_id, seller_id = (uuid4() for _ in range(2))
        seller_order_id = uuid5(NAMESPACE_URL, f"neomarket:seller-order:{buyer_order_id}:{seller_id}")
        try:
            async with sessions() as session:
                order = SimpleNamespace(
                    id=buyer_order_id,
                    items=[SimpleNamespace(seller_id=seller_id)],
                )
                await OrderService(session)._queue_seller_order_cancellations(order)
                await session.commit()

            async with sessions() as session:
                event = await session.scalar(
                    select(SellerOrderOutbox).where(SellerOrderOutbox.seller_order_id == seller_order_id)
                )
                assert event is not None
                assert event.payload["aggregate_id"] == str(seller_order_id)
                assert event.payload["event_type"] == "seller_order.cancelled.v1"
                assert event.payload["payload"]["buyer_order_id"] == str(buyer_order_id)
                assert event.payload["tenant_id"] == str(seller_id)
                assert event.payload["payload_hash"] == hashlib.sha256(
                    json.dumps(event.payload["payload"], sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest()
                assert event.payload_sha256 == hashlib.sha256(
                    json.dumps(event.payload, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest()
                assert event.status == "PENDING"
        finally:
            async with sessions() as session:
                await session.execute(
                    delete(SellerOrderOutbox).where(SellerOrderOutbox.seller_order_id == seller_order_id)
                )
                await session.commit()
            await engine.dispose()

    asyncio.run(scenario())


@pytest.mark.postgres_integration
def test_live_cancellation_outbox_reaches_b2b_and_blocks_allocation() -> None:
    b2c_url = os.getenv("NEOMARKET_POSTGRES_TEST_URL")
    b2b_url = os.getenv("NEOMARKET_B2B_POSTGRES_TEST_URL")
    if not b2c_url or not b2b_url:
        pytest.skip("set both B2C and B2B PostgreSQL URLs for cancellation delivery integration")

    async def scenario() -> None:
        b2c_engine = create_async_engine(b2c_url, poolclass=NullPool)
        b2b_engine = create_async_engine(b2b_url, poolclass=NullPool)
        b2c_sessions = async_sessionmaker(b2c_engine, expire_on_commit=False, class_=AsyncSession)
        b2b_sessions = async_sessionmaker(b2b_engine, expire_on_commit=False, class_=AsyncSession)
        buyer_order_id, seller_id = (uuid4() for _ in range(2))
        seller_order_id = uuid5(NAMESPACE_URL, f"neomarket:seller-order:{buyer_order_id}:{seller_id}")
        event_id = uuid5(
            NAMESPACE_URL, f"neomarket:seller-order-cancellation:{buyer_order_id}:{seller_id}:v1"
        )
        now = datetime.now(timezone.utc)
        email = f"seller-outbox-{uuid4()}@example.com"
        try:
            async with b2b_sessions() as session:
                await session.execute(
                    text("""INSERT INTO sellers (id, email, hashed_password, company_name, is_active, email_verified_at)
                              VALUES (:id, :email, 'fixture-only', 'Cancellation outbox fixture', true, :now)"""),
                    {"id": seller_id, "email": email, "now": now},
                )
                await session.execute(
                    text("""INSERT INTO seller_orders
                              (id, buyer_order_id, seller_id, currency, status, total_minor, revision, allocated_at)
                              VALUES (:id, :buyer, :seller, 'RUB', 'CREATED', 0, 1, :now)"""),
                    {"id": seller_order_id, "buyer": buyer_order_id, "seller": seller_id, "now": now},
                )
                await session.commit()

            async with b2c_sessions() as session:
                await OrderService(session)._queue_seller_order_cancellations(
                    SimpleNamespace(id=buyer_order_id, items=[SimpleNamespace(seller_id=seller_id)])
                )
                await session.commit()
                delivered = await OrderService(session).retry_pending_seller_order_events()
                await session.commit()
                assert delivered == 1
                outbox = await session.get(SellerOrderOutbox, event_id)
                assert outbox is not None and outbox.status == "SENT"

            async with b2b_sessions() as session:
                status_value = await session.scalar(
                    text("SELECT status FROM seller_orders WHERE id = :id"), {"id": seller_order_id}
                )
                assert status_value == "CANCELLED"
        finally:
            async with b2c_sessions() as session:
                await session.execute(delete(SellerOrderOutbox).where(SellerOrderOutbox.event_id == event_id))
                await session.commit()
            async with b2b_sessions() as session:
                await session.execute(text("DELETE FROM inbox_events WHERE event_id = :event"), {"event": event_id})
                await session.execute(text("DELETE FROM seller_orders WHERE id = :id"), {"id": seller_order_id})
                await session.execute(text("DELETE FROM sellers WHERE id = :id"), {"id": seller_id})
                await session.commit()
            await b2c_engine.dispose()
            await b2b_engine.dispose()

    asyncio.run(scenario())
