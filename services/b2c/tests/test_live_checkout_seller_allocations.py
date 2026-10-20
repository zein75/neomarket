import asyncio
import os
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from src.models.address import Address
from src.models.cart import Cart, CartItem
from src.models.order import (
    CheckoutAttempt,
    Order,
    OrderStatus,
    SellerOrderOutbox,
)
from src.models.user import User
from src.clients.b2b_client import B2BClient as RealB2BClient
from src.core.config import settings
from src.schemas.order import OrderCreateRequest
from src.services import order_service as order_service_module
from src.services.order_service import OrderService


@pytest.mark.postgres_integration
@pytest.mark.parametrize("seller_count", [1, 2], ids=["single-seller", "multi-seller"])
def test_live_checkout_persists_one_seller_allocation_per_seller(
    seller_count: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = os.getenv("NEOMARKET_POSTGRES_TEST_URL")
    b2b_database_url = os.getenv("NEOMARKET_B2B_POSTGRES_TEST_URL")
    b2b_url = os.getenv("NEOMARKET_B2B_TEST_URL")
    if not database_url or not b2b_database_url or not b2b_url:
        pytest.skip("set B2C/B2B PostgreSQL and B2B API URLs for checkout allocation integration")

    class LocalB2BFixture:
        products: list[dict[str, object]] = []
        reservations: list[dict[str, object]] = []

        def __init__(self, _base_url: str) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get_products_batch(self, product_ids: list[str]):
            return [product for product in self.products if product["id"] in product_ids]

        async def reserve(self, payload: dict[str, object]):
            self.reservations.append(payload)
            return {"reserved": True}

    monkeypatch.setattr(order_service_module, "B2BClient", LocalB2BFixture)

    async def scenario() -> None:
        engine = create_async_engine(database_url, poolclass=NullPool)
        b2b_engine = create_async_engine(b2b_database_url, poolclass=NullPool)
        sessions = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        b2b_sessions = async_sessionmaker(b2b_engine, expire_on_commit=False, class_=AsyncSession)
        user_id, cart_id, address_id = uuid4(), uuid4(), uuid4()
        product_ids = [uuid4() for _ in range(seller_count)]
        sku_ids = [uuid4() for _ in range(seller_count)]
        seller_ids = [uuid4() for _ in range(seller_count)]
        idempotency_key = f"seller-allocation-{uuid4()}"
        order_id = OrderService._checkout_operation_id(user_id, idempotency_key)
        seller_order_ids = {
            seller_id: uuid5(NAMESPACE_URL, f"neomarket:seller-order:{order_id}:{seller_id}")
            for seller_id in seller_ids
        }
        event_ids = {
            seller_id: uuid5(
                NAMESPACE_URL,
                f"neomarket:seller-order-allocation:{order_id}:{seller_id}:v1",
            )
            for seller_id in seller_ids
        }
        LocalB2BFixture.products = [
            {
                "id": str(product_ids[index]),
                "seller_id": str(seller_ids[index]),
                "title": f"Allocation fixture {index}",
                "skus": [
                    {
                        "id": str(sku_ids[index]),
                        "name": "Local fixture SKU",
                        "price": 1250 + index,
                        "active_quantity": 10,
                    }
                ],
            }
            for index in range(seller_count)
        ]
        LocalB2BFixture.reservations = []
        cart_item_ids = [uuid4() for _ in range(seller_count)]
        try:
            async with sessions() as session:
                buyer = User(id=user_id, email=f"checkout-{uuid4()}@example.test", hashed_password="fixture-only")
                address = Address(
                    id=address_id,
                    user_id=user_id,
                    country="RU",
                    city="Local test",
                    street="Test street",
                    building="1",
                )
                cart = Cart(id=cart_id, user_id=user_id, currency="RUB")
                session.add_all([buyer, address, cart])
                await session.flush()
                session.add_all(
                    [
                        CartItem(
                            id=cart_item_ids[index],
                            cart_id=cart_id,
                            sku_id=sku_ids[index],
                            product_id=product_ids[index],
                            quantity=index + 1,
                            unit_price=1,
                        )
                        for index in range(seller_count)
                    ]
                )
                await session.commit()

                order = await OrderService(session).checkout(
                    user_id=user_id,
                    cart_id=cart_id,
                    idempotency_key=idempotency_key,
                    order_request=OrderCreateRequest(
                        address_id=address_id,
                        payment_method_id=uuid4(),
                    ),
                )
                assert order.id == order_id
                assert order.status == OrderStatus.CREATED
                assert {item.seller_id for item in order.items} == set(seller_ids)
                assert len(LocalB2BFixture.reservations) == 1

                allocations = list(
                    (
                        await session.execute(
                            select(SellerOrderOutbox)
                            .where(SellerOrderOutbox.payload["correlation_id"].as_string() == str(order_id))
                        )
                    ).scalars().all()
                )
                assert len(allocations) == seller_count
                assert {row.payload["tenant_id"] for row in allocations} == {
                    str(seller_id) for seller_id in seller_ids
                }
                for allocation in allocations:
                    payload = allocation.payload["payload"]
                    assert payload["buyer_order_id"] == str(order_id)
                    assert payload["status"] == "CREATED"
                    assert payload["items"]
                    assert "address" not in payload and "contact" not in payload
                assert sum(len(row.payload["payload"]["items"]) for row in allocations) == seller_count

                async with b2b_sessions() as b2b_session:
                    for seller_id in seller_ids:
                        await b2b_session.execute(
                            text("""INSERT INTO sellers
                                   (id, email, hashed_password, company_name, is_active, account_status)
                                   VALUES (:id, :email, 'fixture-only', 'Checkout allocation fixture', true, 'ACTIVE')"""),
                            {"id": seller_id, "email": f"checkout-seller-{uuid4()}@example.test"},
                        )
                    await b2b_session.commit()

                async with RealB2BClient(settings.b2b_base_url) as b2b_client:
                    for allocation in allocations:
                        await b2b_client.send_seller_order_allocation(allocation.payload)
                        allocation.status = "SENT"
                        allocation.attempts += 1
                await session.commit()

                async with b2b_sessions() as b2b_session:
                    for seller_id in seller_ids:
                        persisted = await b2b_session.execute(
                            text("SELECT seller_id, buyer_order_id, status, total_minor FROM seller_orders WHERE id = :id"),
                            {"id": seller_order_ids[seller_id]},
                        )
                        row = persisted.mappings().one()
                        assert row["seller_id"] == seller_id
                        assert row["buyer_order_id"] == order_id
                        assert row["status"] == "CREATED"
                        line_count = await b2b_session.scalar(
                            text("SELECT count(*) FROM seller_order_items WHERE seller_order_id = :id"),
                            {"id": seller_order_ids[seller_id]},
                        )
                        assert line_count == 1
                        inbox_count = await b2b_session.scalar(
                            text("SELECT count(*) FROM inbox_events WHERE producer = 'b2c' AND event_id = :event_id"),
                            {"event_id": event_ids[seller_id]},
                        )
                        assert inbox_count == 1
                assert all(row.status == "SENT" for row in allocations)
        finally:
            async with b2b_sessions() as session:
                for seller_id in seller_ids:
                    seller_order_id = seller_order_ids[seller_id]
                    await session.execute(
                        text("DELETE FROM seller_order_items WHERE seller_order_id = :id"),
                        {"id": seller_order_id},
                    )
                    await session.execute(
                        text("DELETE FROM seller_orders WHERE id = :id"),
                        {"id": seller_order_id},
                    )
                    await session.execute(
                        text("DELETE FROM inbox_events WHERE producer = 'b2c' AND event_id = :id"),
                        {"id": event_ids[seller_id]},
                    )
                    await session.execute(text("DELETE FROM sellers WHERE id = :id"), {"id": seller_id})
                await session.commit()
            async with sessions() as session:
                await session.execute(
                    delete(SellerOrderOutbox).where(
                        SellerOrderOutbox.payload["correlation_id"].as_string() == str(order_id)
                    )
                )
                await session.execute(delete(CheckoutAttempt).where(CheckoutAttempt.attempt_id == order_id))
                await session.execute(delete(Order).where(Order.id == order_id))
                await session.execute(delete(CartItem).where(CartItem.cart_id == cart_id))
                await session.execute(delete(Cart).where(Cart.id == cart_id))
                await session.execute(delete(Address).where(Address.id == address_id))
                await session.execute(delete(User).where(User.id == user_id))
                await session.commit()
            async with sessions() as session:
                assert await session.scalar(select(func.count()).select_from(Order).where(Order.id == order_id)) == 0
                assert await session.scalar(
                    select(func.count()).select_from(SellerOrderOutbox).where(
                        SellerOrderOutbox.payload["correlation_id"].as_string() == str(order_id)
                    )
                ) == 0
                assert await session.scalar(select(func.count()).select_from(User).where(User.id == user_id)) == 0
            async with b2b_sessions() as session:
                for seller_id in seller_ids:
                    assert await session.scalar(
                        text("SELECT count(*) FROM seller_orders WHERE id = :id"),
                        {"id": seller_order_ids[seller_id]},
                    ) == 0
                    assert await session.scalar(
                        text("SELECT count(*) FROM inbox_events WHERE producer = 'b2c' AND event_id = :id"),
                        {"id": event_ids[seller_id]},
                    ) == 0
            await engine.dispose()
            await b2b_engine.dispose()

    asyncio.run(scenario())
