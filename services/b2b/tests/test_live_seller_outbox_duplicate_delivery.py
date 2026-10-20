import asyncio
import os
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.clients.moderation import ModerationClient
from src.core.security import hash_password
from src.models.base import Base
from src.models.outbox_event import OutboxEvent
from src.models.product import Product
from src.models.seller import Seller
from src.models.sku import SKU
from src.repositories.outbox_event_repo import OutboxEventRepository
from src.services.reservation_service import ReservationService


@pytest.mark.postgres_integration
def test_live_product_outbox_recovers_after_consumer_commit_and_lost_ack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    postgres_admin_url = os.getenv("NEOMARKET_POSTGRES_ADMIN_URL")
    admin_database_url = os.getenv("NEOMARKET_ADMIN_POSTGRES_TEST_URL")
    if not postgres_admin_url or not admin_database_url:
        pytest.skip("set isolated/local B2B and Admin PostgreSQL URLs for outbox integration")

    async def scenario() -> None:
        temporary_database = f"seller_outbox_{uuid4().hex[:12]}"
        postgres_engine = create_async_engine(postgres_admin_url, isolation_level="AUTOCOMMIT")
        admin_engine = create_async_engine(admin_database_url)
        async with postgres_engine.connect() as connection:
            await connection.execute(text(f'CREATE DATABASE "{temporary_database}"'))
        b2b_database_url = f"{postgres_admin_url.rsplit('/', 1)[0]}/{temporary_database}"
        b2b_engine = create_async_engine(b2b_database_url)
        async with b2b_engine.begin() as connection:
            await connection.run_sync(
                lambda sync_connection: Base.metadata.create_all(
                    sync_connection,
                    tables=[Seller.__table__, Product.__table__, SKU.__table__, OutboxEvent.__table__],
                )
            )
        b2b_sessions = async_sessionmaker(b2b_engine, expire_on_commit=False, class_=AsyncSession)
        seller_id, product_id, sku_id = uuid4(), uuid4(), uuid4()
        try:
            async with b2b_sessions() as session:
                seller = Seller(
                    id=seller_id,
                    email=f"seller-outbox-{uuid4()}@example.com",
                    hashed_password=hash_password("DisposableOutbox!2026"),
                    company_name="Disposable outbox integration seller",
                    is_active=True,
                    account_status="ACTIVE",
                    email_verified_at=datetime.now(timezone.utc),
                )
                product = Product(
                    id=product_id,
                    seller=seller,
                    title="Outbox duplicate delivery fixture",
                    slug=Product.make_slug("Outbox duplicate delivery fixture", product_id),
                    description="Disposable integration fixture",
                    images=[],
                    characteristics={},
                    status="ON_MODERATION",
                    is_active=False,
                    deleted=False,
                    revision=1,
                )
                sku = SKU(
                    id=sku_id,
                    product=product,
                    name="Fixture variant",
                    price=1299,
                    stock=2,
                    on_hand=2,
                    reserved_quantity=0,
                    images=[],
                    is_active=True,
                    revision=1,
                )
                session.add_all([seller, product, sku])
                await session.flush()
                event = ModerationClient().build_product_created_event(product)
                outbox = await OutboxEventRepository(session).create_event(
                    destination="MODERATION",
                    idempotency_key=event["idempotency_key"],
                    event_type=event["event_type"],
                    payload=event,
                )
                assert outbox is not None
                outbox_id, event_id = outbox.id, event["idempotency_key"]
                await session.commit()

            delivery_count = 0
            real_delivery = ModerationClient._post_event

            async def deliver_then_drop_first_ack(client: ModerationClient, payload: dict[str, object]) -> None:
                nonlocal delivery_count
                await real_delivery(client, payload)
                delivery_count += 1
                if delivery_count == 1:
                    raise httpx.ReadTimeout("synthetic lost acknowledgement after Admin commit")

            monkeypatch.setattr(ModerationClient, "_post_event", deliver_then_drop_first_ack)
            async with b2b_sessions() as session:
                service = ReservationService(session)
                assert await service.retry_pending_outbox(limit=1) == 0
                await session.commit()
                pending = await session.get(OutboxEvent, outbox_id)
                assert pending is not None and pending.status == "PENDING" and pending.attempts == 1

                redelivered = await service.retry_pending_outbox(limit=1)
                assert redelivered == 1
                await session.commit()
                sent = await session.get(OutboxEvent, outbox_id)
                assert sent is not None and sent.status == "SENT" and sent.attempts == 2

            async with admin_engine.connect() as connection:
                processed = await connection.scalar(
                    text("SELECT count(*) FROM processed_product_events WHERE event_id = :event_id"),
                    {"event_id": event_id},
                )
                tickets = await connection.scalar(
                    text("SELECT count(*) FROM moderation_cards WHERE product_id = :product_id"),
                    {"product_id": product_id},
                )
                assert processed == 1
                assert tickets == 1
        finally:
            async with b2b_sessions() as session:
                await session.execute(delete(OutboxEvent).where(OutboxEvent.aggregate_id == product_id))
                product = await session.get(Product, product_id)
                if product is not None:
                    await session.delete(product)
                seller = await session.get(Seller, seller_id)
                if seller is not None:
                    await session.delete(seller)
                await session.commit()
            async with admin_engine.begin() as connection:
                ticket_ids = list((await connection.scalars(
                    text("SELECT id FROM moderation_cards WHERE product_id = :product_id"),
                    {"product_id": product_id},
                )).all())
                if ticket_ids:
                    await connection.execute(
                        text("DELETE FROM moderation_skus WHERE card_id = ANY(:ticket_ids)"),
                        {"ticket_ids": ticket_ids},
                    )
                    await connection.execute(
                        text("DELETE FROM moderation_snapshots WHERE ticket_id = ANY(:ticket_ids)"),
                        {"ticket_ids": ticket_ids},
                    )
                    await connection.execute(
                        text("DELETE FROM moderation_cards WHERE id = ANY(:ticket_ids)"),
                        {"ticket_ids": ticket_ids},
                    )
                await connection.execute(
                    text("DELETE FROM processed_product_events WHERE event_id = :event_id"),
                    {"event_id": event_id},
                )
                # Admin's integrity-chained audit receipt is intentionally retained.
            await b2b_engine.dispose()
            await admin_engine.dispose()
            async with postgres_engine.connect() as connection:
                await connection.execute(text(f'DROP DATABASE IF EXISTS "{temporary_database}"'))
            await postgres_engine.dispose()

    asyncio.run(scenario())
