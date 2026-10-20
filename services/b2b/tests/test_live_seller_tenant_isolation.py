import asyncio
import os
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.core.security import hash_password
from src.models.product import Product
from src.models.seller import Seller
from src.models.seller_order import SellerOrder, SellerOrderItem
from src.models.sku import SKU
from src.models.stock_adjustment import StockAdjustment
from src.models.seller_membership import SellerMembership
from src.models.seller_user import SellerUser


@pytest.mark.postgres_integration
def test_live_b2b_rejects_foreign_product_sku_adjustment_and_order() -> None:
    database_url = os.getenv("NEOMARKET_POSTGRES_TEST_URL")
    b2b_url = os.getenv("NEOMARKET_B2B_TEST_URL")
    if not database_url or not b2b_url:
        pytest.skip("set PostgreSQL and B2B test URLs for tenant-isolation integration")

    async def scenario() -> None:
        engine = create_async_engine(database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        seller_a_id, seller_b_id = uuid4(), uuid4()
        user_a_id, user_b_id = uuid4(), uuid4()
        product_id, sku_id, order_id = uuid4(), uuid4(), uuid4()
        email_a = f"tenant-a-{uuid4()}@example.com"
        email_b = f"tenant-b-{uuid4()}@example.com"
        password = "DisposableTenant!2026"
        try:
            async with sessions() as session:
                owner_a = Seller(
                    id=seller_a_id,
                    email=email_a,
                    hashed_password=hash_password(password),
                    company_name="Tenant A integration fixture",
                    is_active=True,
                    account_status="ACTIVE",
                    email_verified_at=datetime.now(timezone.utc),
                )
                owner_b = Seller(
                    id=seller_b_id,
                    email=email_b,
                    hashed_password=hash_password(password),
                    company_name="Tenant B integration fixture",
                    is_active=True,
                    account_status="ACTIVE",
                    email_verified_at=datetime.now(timezone.utc),
                )
                user_a = SellerUser(
                    id=user_a_id,
                    email=email_a,
                    hashed_password=hash_password(password),
                    is_active=True,
                    email_verified_at=datetime.now(timezone.utc),
                )
                user_b = SellerUser(
                    id=user_b_id,
                    email=email_b,
                    hashed_password=hash_password(password),
                    is_active=True,
                    email_verified_at=datetime.now(timezone.utc),
                )
                session.add_all([owner_a, owner_b, user_a, user_b])
                await session.flush()
                session.add_all([
                    SellerMembership(seller_id=seller_a_id, user_id=user_a_id, role="OWNER", active=True),
                    SellerMembership(seller_id=seller_b_id, user_id=user_b_id, role="OWNER", active=True),
                ])
                product = Product(
                    id=product_id,
                    seller=owner_b,
                    title="Disposable tenant isolation product",
                    images=[],
                    characteristics={},
                    status="CREATED",
                    is_active=False,
                    deleted=False,
                    revision=1,
                )
                sku = SKU(
                    id=sku_id,
                    product=product,
                    name="Disposable tenant isolation SKU",
                    price=100,
                    stock=10,
                    on_hand=10,
                    reserved_quantity=0,
                    images=[],
                    is_active=True,
                    revision=1,
                )
                order = SellerOrder(
                    id=order_id,
                    buyer_order_id=uuid4(),
                    seller_id=seller_b_id,
                    currency="RUB",
                    status="CREATED",
                    total_minor=100,
                    revision=1,
                    allocated_at=datetime.now(timezone.utc),
                    items=[
                        SellerOrderItem(
                            sku_id=sku_id,
                            product_id=product_id,
                            product_title=product.title,
                            sku_name=sku.name,
                            quantity=1,
                            unit_price_minor=100,
                            line_total_minor=100,
                        )
                    ],
                )
                session.add_all([product, sku, order])
                await session.commit()

            with httpx.Client(base_url=b2b_url, timeout=10) as client:
                login_a = client.post(
                    "/auth/login", data={"username": email_a, "password": password}
                )
                login_b = client.post(
                    "/auth/login", data={"username": email_b, "password": password}
                )
                assert login_a.status_code == login_b.status_code == 200
                headers_a = {"Authorization": f"Bearer {login_a.json()['access_token']}"}
                headers_b = {"Authorization": f"Bearer {login_b.json()['access_token']}"}

                assert client.get(
                    f"/api/v1/products/{product_id}", headers=headers_b
                ).status_code == 200
                assert client.get(
                    f"/api/v1/seller/skus/{sku_id}", headers=headers_b
                ).status_code == 200
                assert client.get(
                    f"/api/v1/seller/orders/{order_id}", headers=headers_b
                ).status_code == 200

                seller_a_products = client.get(
                    "/api/v1/seller/products?limit=100&include_skus=true", headers=headers_a
                )
                assert seller_a_products.status_code == 200
                assert all(item["id"] != str(product_id) for item in seller_a_products.json()["items"])
                seller_a_inventory = client.get(
                    "/api/v1/seller/inventory?limit=100", headers=headers_a
                )
                assert seller_a_inventory.status_code == 200
                assert all(item["sku_id"] != str(sku_id) for item in seller_a_inventory.json()["items"])
                seller_a_orders = client.get(
                    "/api/v1/seller/orders?limit=100", headers=headers_a
                )
                assert seller_a_orders.status_code == 200
                assert all(item["id"] != str(order_id) for item in seller_a_orders.json()["items"])
                assert client.get(
                    "/api/v1/seller/products/%s/moderation" % product_id, headers=headers_a
                ).status_code == 404
                assert client.get(
                    f"/api/v1/seller/inventory/imports/{uuid4()}", headers=headers_a
                ).status_code == 404

                assert client.get(
                    f"/api/v1/products/{product_id}", headers=headers_a
                ).status_code == 404
                adjustment = client.post(
                    f"/api/v1/seller/skus/{sku_id}/stock-adjustments",
                    headers={**headers_a, "Idempotency-Key": str(uuid4())},
                    json={"delta": 1, "reason": "count correction"},
                )
                assert adjustment.status_code == 404
                assert client.get(
                    f"/api/v1/seller/orders/{order_id}", headers=headers_a
                ).status_code == 404

            async with sessions() as session:
                persisted_sku = await session.get(SKU, sku_id)
                assert persisted_sku is not None and persisted_sku.on_hand == 10
                adjustments = await session.execute(
                    select(StockAdjustment).where(StockAdjustment.sku_id == sku_id)
                )
                assert adjustments.scalars().all() == []
        finally:
            async with sessions() as session:
                product = await session.get(Product, product_id)
                if product is not None:
                    await session.delete(product)
                order = await session.get(SellerOrder, order_id)
                if order is not None:
                    await session.delete(order)
                for seller_id in (seller_a_id, seller_b_id):
                    seller = await session.get(Seller, seller_id)
                    if seller is not None:
                        await session.delete(seller)
                for user_id in (user_a_id, user_b_id):
                    user = await session.get(SellerUser, user_id)
                    if user is not None:
                        await session.delete(user)
                await session.commit()
            await engine.dispose()

    asyncio.run(scenario())
