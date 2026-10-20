import asyncio
import os
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload
from sqlalchemy.pool import NullPool

from src.models.order import Order, OrderItem, OrderStatus, SellerOrderOutbox
from src.models.user import User
from src.services.order_service import OrderService


@pytest.mark.postgres_integration
def test_live_seller_suspension_does_not_mutate_buyer_order() -> None:
    b2c_url = os.getenv("NEOMARKET_POSTGRES_TEST_URL")
    b2b_url = os.getenv("NEOMARKET_B2B_POSTGRES_TEST_URL")
    if not b2c_url or not b2b_url:
        pytest.skip("set both B2C and B2B PostgreSQL URLs for seller suspension integration")

    async def scenario() -> None:
        b2c_engine = create_async_engine(b2c_url, poolclass=NullPool)
        b2b_engine = create_async_engine(b2b_url, poolclass=NullPool)
        b2c_sessions = async_sessionmaker(b2c_engine, expire_on_commit=False, class_=AsyncSession)
        b2b_sessions = async_sessionmaker(b2b_engine, expire_on_commit=False, class_=AsyncSession)
        user_id, seller_id, order_id, item_id = (uuid4() for _ in range(4))
        buyer_order_id = order_id
        seller_order_id = uuid5(NAMESPACE_URL, f"neomarket:seller-order:{buyer_order_id}:{seller_id}")
        email = f"buyer-suspension-{uuid4()}@example.com"
        try:
            async with b2b_sessions() as session:
                await session.execute(
                    text("""INSERT INTO sellers (id, email, hashed_password, company_name, is_active, account_status)
                              VALUES (:id, :email, 'fixture-only', 'Suspension fixture', true, 'ACTIVE')"""),
                    {"id": seller_id, "email": f"seller-{uuid4()}@example.com"},
                )
                await session.commit()

            async with b2c_sessions() as session:
                buyer = User(id=user_id, email=email, hashed_password="fixture-only", is_active=True)
                item = OrderItem(
                    id=item_id,
                    sku_id=uuid4(),
                    product_id=uuid4(),
                    seller_id=seller_id,
                    product_title="Suspension isolation fixture",
                    sku_name="One unit",
                    quantity=1,
                    unit_price=900,
                    line_total=900,
                )
                order = Order(
                    id=order_id,
                    user_id=user_id,
                    status=OrderStatus.PAID,
                    total_amount=900,
                    currency="RUB",
                    address_id=uuid4(),
                    address={"city": "Local test"},
                    idempotency_key=f"suspension-{uuid4()}",
                    items=[item],
                )
                session.add_all([buyer, order])
                await session.commit()
                await OrderService(session)._queue_seller_order_allocations(order)
                await session.commit()

            async with b2b_sessions() as session:
                await session.execute(
                    text("UPDATE sellers SET account_status = 'SUSPENDED', is_active = false WHERE id = :id"),
                    {"id": seller_id},
                )
                await session.commit()

            async with b2c_sessions() as session:
                persisted = await session.scalar(
                    select(Order).options(selectinload(Order.items)).where(Order.id == order_id)
                )
                assert persisted is not None and persisted.status == OrderStatus.PAID
                assert persisted.items[0].seller_id == seller_id
                assert persisted.items[0].line_total == 900
                queued = list(
                    (
                        await session.execute(
                            select(SellerOrderOutbox).where(
                                SellerOrderOutbox.seller_order_id == seller_order_id
                            )
                        )
                    ).scalars().all()
                )
                assert len(queued) == 1
                assert queued[0].payload["event_type"] == "seller_order.allocated.v1"
        finally:
            async with b2c_sessions() as session:
                await session.execute(delete(SellerOrderOutbox).where(SellerOrderOutbox.seller_order_id == seller_order_id))
                await session.execute(delete(Order).where(Order.id == order_id))
                await session.execute(delete(User).where(User.id == user_id))
                await session.commit()
            async with b2b_sessions() as session:
                await session.execute(text("DELETE FROM sellers WHERE id = :id"), {"id": seller_id})
                await session.commit()
            await b2c_engine.dispose()
            await b2b_engine.dispose()

    asyncio.run(scenario())
