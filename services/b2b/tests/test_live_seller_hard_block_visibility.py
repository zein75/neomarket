import asyncio
import os
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.core.config import settings
from src.models.inbox_event import InboxEvent
from src.models.inventory_ledger import InventoryLedger
from src.models.outbox_event import OutboxEvent
from src.models.processed_event import ProcessedEvent
from src.models.product import Product, ProductStatus
from src.models.seller import Seller
from src.models.sku import SKU


@pytest.mark.postgres_integration
def test_live_hard_block_hides_product_from_public_api() -> None:
    database_url = os.getenv("NEOMARKET_POSTGRES_TEST_URL")
    b2b_url = os.getenv("NEOMARKET_B2B_TEST_URL")
    if not database_url or not b2b_url:
        pytest.skip("set PostgreSQL and B2B URLs for product visibility integration")

    async def scenario() -> None:
        engine = create_async_engine(database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        seller_id, product_id, sku_id = uuid4(), uuid4(), uuid4()
        event_id, ticket_id, actor_id, correlation_id = uuid4(), uuid4(), uuid4(), uuid4()
        email = f"hard-block-{uuid4()}@example.com"
        now = datetime.now(timezone.utc)
        try:
            async with sessions() as session:
                session.add(
                    Seller(
                        id=seller_id,
                        email=email,
                        hashed_password="unused-integration-password-hash",
                        company_name="Disposable hard block seller",
                        is_active=True,
                        account_status="ACTIVE",
                        email_verified_at=now,
                    )
                )
                session.add(
                    Product(
                        id=product_id,
                        seller_id=seller_id,
                        title="Disposable hard block visibility fixture",
                        description="Visible only before hard block",
                        category_id=None,
                        images=[],
                        characteristics={},
                        status=ProductStatus.MODERATED,
                        is_active=True,
                        deleted=False,
                        revision=1,
                    )
                )
                session.add(
                    SKU(
                        id=sku_id,
                        product_id=product_id,
                        name="Visibility fixture SKU",
                        price=100,
                        stock=2,
                        on_hand=2,
                        reserved_quantity=0,
                        images=[],
                        is_active=True,
                        revision=1,
                    )
                )
                await session.commit()

            headers = {"X-Service-Key": settings.service_key}
            with httpx.Client(timeout=20) as client:
                public_url = f"{b2b_url}/api/v1/public/products/{product_id}"
                visible = client.get(public_url, headers=headers)
                assert visible.status_code == 200, visible.text
                blocked = client.post(
                    f"{b2b_url}/internal/v1/events/moderation",
                    headers=headers,
                    json={
                        "schema_version": 1,
                        "event_id": str(event_id),
                        "event_type": "moderation.blocked",
                        "producer": "admin",
                        "aggregate_type": "moderation_ticket",
                        "aggregate_id": str(ticket_id),
                        "aggregate_version": 1,
                        "occurred_at": now.isoformat(),
                        "correlation_id": str(correlation_id),
                        "payload": {
                            "product_id": str(product_id),
                            "reviewed_revision": 1,
                            "decision_id": str(uuid4()),
                            "ticket_id": str(ticket_id),
                            "actor_id": str(actor_id),
                            "action": "HARD_BLOCK",
                        },
                    },
                )
                assert blocked.status_code == 202, blocked.text
                hidden = client.get(public_url, headers=headers)
                assert hidden.status_code == 404

            async with sessions() as session:
                product = await session.get(Product, product_id)
                assert product is not None
                assert product.status == ProductStatus.HARD_BLOCKED
                assert product.is_active is False
        finally:
            async with sessions() as session:
                await session.execute(delete(OutboxEvent).where(OutboxEvent.aggregate_id == product_id))
                await session.execute(delete(ProcessedEvent).where(ProcessedEvent.idempotency_key == str(event_id)))
                await session.execute(delete(InboxEvent).where(InboxEvent.event_id == event_id))
                await session.execute(delete(InventoryLedger).where(InventoryLedger.sku_id == sku_id))
                await session.execute(delete(SKU).where(SKU.id == sku_id))
                await session.execute(delete(Product).where(Product.id == product_id))
                await session.execute(delete(Seller).where(Seller.id == seller_id))
                await session.commit()
            await engine.dispose()

    asyncio.run(scenario())
