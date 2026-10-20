import asyncio
import os
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.core.security import hash_password
from src.models.seller import Seller
from src.models.seller_membership import SellerMembership
from src.models.seller_order import SellerOrder, SellerOrderItem
from src.models.seller_shipment import SellerShipment, SellerShipmentLine
from src.models.seller_user import SellerUser


@pytest.mark.postgres_integration
def test_live_seller_order_acceptance_is_idempotent_and_owner_scoped() -> None:
    database_url = os.getenv("NEOMARKET_POSTGRES_TEST_URL")
    b2b_url = os.getenv("NEOMARKET_B2B_TEST_URL")
    if not database_url or not b2b_url:
        pytest.skip("set PostgreSQL and B2B URLs for seller order integration")

    async def scenario() -> None:
        engine = create_async_engine(database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        seller_id, user_id, support_user_id, other_seller_id, other_user_id, order_id = (uuid4() for _ in range(6))
        emails = [f"seller-order-{uuid4()}@example.com", f"seller-order-support-{uuid4()}@example.com", f"seller-order-other-{uuid4()}@example.com"]
        password = "DisposableOrder!2026"
        try:
            async with sessions() as session:
                digest = hash_password(password)
                now = datetime.now(timezone.utc)
                seller = Seller(id=seller_id, email=emails[0], hashed_password=digest, company_name="Order receipt fixture", is_active=True, account_status="ACTIVE", email_verified_at=now)
                user = SellerUser(id=user_id, email=emails[0], hashed_password=digest, is_active=True, email_verified_at=now)
                support_user = SellerUser(id=support_user_id, email=emails[1], hashed_password=digest, is_active=True, email_verified_at=now)
                other_seller = Seller(id=other_seller_id, email=emails[2], hashed_password=digest, company_name="Other seller fixture", is_active=True, account_status="ACTIVE", email_verified_at=now)
                other_user = SellerUser(id=other_user_id, email=emails[2], hashed_password=digest, is_active=True, email_verified_at=now)
                order = SellerOrder(
                    id=order_id, buyer_order_id=uuid4(), seller_id=seller_id, currency="RUB", status="CREATED",
                    total_minor=2598, revision=1, allocated_at=now,
                    items=[SellerOrderItem(sku_id=uuid4(), product_id=uuid4(), product_title="Receipt fixture", sku_name="Fixture SKU", quantity=2, unit_price_minor=1299, line_total_minor=2598)],
                )
                session.add_all([seller, user, support_user, other_seller, other_user, order])
                await session.flush()
                session.add_all([
                    SellerMembership(seller_id=seller_id, user_id=user_id, role="OWNER", active=True),
                    SellerMembership(seller_id=seller_id, user_id=support_user_id, role="SUPPORT", active=True),
                    SellerMembership(seller_id=other_seller_id, user_id=other_user_id, role="OWNER", active=True),
                ])
                await session.commit()

            with httpx.Client(base_url=b2b_url, timeout=15) as client:
                login = client.post("/auth/login", data={"username": emails[0], "password": password})
                assert login.status_code == 200, login.text
                headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
                owner_permissions = client.get("/auth/permissions", headers=headers)
                assert owner_permissions.status_code == 200, owner_permissions.text
                assert owner_permissions.json()["role"] == "OWNER"
                assert "orders.fulfill" in owner_permissions.json()["permissions"]
                disabled = client.post(f"/api/v1/seller/orders/{order_id}/accept", headers=headers)
                assert disabled.status_code == 503, disabled.text
                assert disabled.json()["code"] == "COMMERCIAL_FLOW_DISABLED"
                assert disabled.json()["detail"]["flow"] == "seller_order_acceptance"

                packed = client.post(
                    f"/api/v1/seller/orders/{order_id}/shipments",
                    headers={**headers, "Idempotency-Key": str(uuid4())},
                    json={"lines": [{"seller_order_item_id": str(uuid4()), "quantity": 1}]},
                )
                assert packed.status_code == 503, packed.text
                assert packed.json()["code"] == "COMMERCIAL_FLOW_DISABLED"
                assert packed.json()["detail"]["flow"] == "seller_packing_manifest"

                refreshed = client.get(f"/api/v1/seller/orders/{order_id}", headers=headers)
                assert refreshed.status_code == 200, refreshed.text
                assert refreshed.json()["seller_accepted_at"] is None
                assert refreshed.json()["revision"] == 1
                assert refreshed.json()["shipments"] == []

                support_login = client.post("/auth/login", data={"username": emails[1], "password": password})
                assert support_login.status_code == 200, support_login.text
                support_headers = {"Authorization": f"Bearer {support_login.json()['access_token']}"}
                support_permissions = client.get("/auth/permissions", headers=support_headers)
                assert support_permissions.status_code == 200, support_permissions.text
                assert support_permissions.json()["role"] == "SUPPORT"
                assert "orders.fulfill" not in support_permissions.json()["permissions"]
                support_denied = client.post(f"/api/v1/seller/orders/{order_id}/accept", headers=support_headers)
                assert support_denied.status_code == 403, support_denied.text

                other_login = client.post("/auth/login", data={"username": emails[2], "password": password})
                assert other_login.status_code == 200, other_login.text
                other_headers = {"Authorization": f"Bearer {other_login.json()['access_token']}"}
                denied = client.post(f"/api/v1/seller/orders/{order_id}/accept", headers=other_headers)
                assert denied.status_code == 404, denied.text

            async with sessions() as session:
                saved = await session.get(SellerOrder, order_id)
                assert saved is not None and saved.seller_accepted_at is None and saved.revision == 1
                assert await session.scalar(select(func.count()).select_from(SellerShipment).where(SellerShipment.seller_order_id == order_id)) == 0
        finally:
            async with sessions() as session:
                shipment_ids = select(SellerShipment.id).where(SellerShipment.seller_order_id == order_id)
                await session.execute(delete(SellerShipmentLine).where(SellerShipmentLine.shipment_id.in_(shipment_ids)))
                await session.execute(delete(SellerShipment).where(SellerShipment.seller_order_id == order_id))
                order = await session.get(SellerOrder, order_id)
                if order is not None:
                    await session.delete(order)
                await session.execute(delete(SellerMembership).where(SellerMembership.seller_id.in_([seller_id, other_seller_id])))
                for seller_key in (seller_id, other_seller_id):
                    seller = await session.get(Seller, seller_key)
                    if seller is not None:
                        await session.delete(seller)
                for user_key in (user_id, support_user_id, other_user_id):
                    user = await session.get(SellerUser, user_key)
                    if user is not None:
                        await session.delete(user)
                await session.commit()
            await engine.dispose()

    asyncio.run(scenario())
