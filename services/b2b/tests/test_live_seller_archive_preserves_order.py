import asyncio
import os
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.core.security import hash_password
from src.models.outbox_event import OutboxEvent
from src.models.product import Product
from src.models.seller import Seller
from src.models.seller_membership import SellerMembership
from src.models.seller_order import SellerOrder, SellerOrderItem
from src.models.seller_user import SellerUser
from src.models.sku import SKU


@pytest.mark.postgres_integration
def test_live_archiving_product_preserves_seller_order_snapshot() -> None:
    database_url = os.getenv("NEOMARKET_POSTGRES_TEST_URL")
    b2b_url = os.getenv("NEOMARKET_B2B_TEST_URL")
    if not database_url or not b2b_url:
        pytest.skip("set PostgreSQL and B2B URLs for seller archive integration")

    async def scenario() -> None:
        engine = create_async_engine(database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        seller_id, user_id, product_id, sku_id, order_id = (uuid4() for _ in range(5))
        email = f"seller-archive-{uuid4()}@example.com"
        password = "DisposableArchive!2026"
        title, sku_name = "Historical product name", "Historical SKU name"
        try:
            async with sessions() as session:
                digest = hash_password(password)
                now = datetime.now(timezone.utc)
                seller = Seller(id=seller_id, email=email, hashed_password=digest, company_name="Disposable archive seller", is_active=True, account_status="ACTIVE", email_verified_at=now)
                user = SellerUser(id=user_id, email=email, hashed_password=digest, is_active=True, email_verified_at=now)
                product = Product(id=product_id, seller=seller, title=title, slug=Product.make_slug(title, product_id), images=[], characteristics={}, status="MODERATED", is_active=True, deleted=False, revision=1)
                sku = SKU(id=sku_id, product=product, name=sku_name, price=1299, stock=4, on_hand=4, reserved_quantity=0, images=[], is_active=True, revision=1)
                order = SellerOrder(id=order_id, buyer_order_id=uuid4(), seller_id=seller_id, currency="RUB", status="CREATED", total_minor=2598, revision=1, allocated_at=now, items=[SellerOrderItem(sku_id=sku_id, product_id=product_id, product_title=title, sku_name=sku_name, quantity=2, unit_price_minor=1299, line_total_minor=2598)])
                session.add_all([seller, user, product, sku, order])
                await session.flush()
                session.add(SellerMembership(seller_id=seller_id, user_id=user_id, role="OWNER", active=True))
                await session.commit()

            with httpx.Client(base_url=b2b_url, timeout=15) as client:
                login = client.post("/auth/login", data={"username": email, "password": password})
                assert login.status_code == 200, login.text
                headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
                archived = client.delete(f"/api/v1/seller/products/{product_id}", headers=headers)
                assert archived.status_code == 202, archived.text
                response = client.get(f"/api/v1/seller/orders/{order_id}", headers=headers)
                assert response.status_code == 200, response.text
                item = response.json()["items"][0]
                assert item == {
                    "id": item["id"], "sku_id": str(sku_id), "product_id": str(product_id),
                    "product_title": title, "sku_name": sku_name, "quantity": 2,
                    "unit_price_minor": 1299, "line_total_minor": 2598,
                }

            async with sessions() as session:
                archived_product = await session.get(Product, product_id)
                persisted_order = await session.get(SellerOrder, order_id)
                assert archived_product is not None and archived_product.deleted and not archived_product.is_active
                assert persisted_order is not None and persisted_order.items[0].product_title == title
                assert persisted_order.items[0].sku_name == sku_name
        finally:
            async with sessions() as session:
                await session.execute(delete(OutboxEvent).where(OutboxEvent.aggregate_id == product_id))
                product = await session.get(Product, product_id)
                if product is not None:
                    await session.delete(product)
                order = await session.get(SellerOrder, order_id)
                if order is not None:
                    await session.delete(order)
                await session.execute(delete(SellerMembership).where(SellerMembership.seller_id == seller_id))
                seller = await session.get(Seller, seller_id)
                if seller is not None:
                    await session.delete(seller)
                user = await session.get(SellerUser, user_id)
                if user is not None:
                    await session.delete(user)
                await session.commit()
            await engine.dispose()

    asyncio.run(scenario())
