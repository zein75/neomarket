import asyncio
import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from src.core.database import get_db
from src.core.security import hash_password
from src.main import app
from src.models.local_carrier_label import LocalCarrierLabel
from src.models.seller import Seller
from src.models.seller_carrier_operation import SellerCarrierOperation
from src.models.seller_membership import SellerMembership
from src.models.seller_order import SellerOrder, SellerOrderItem
from src.models.seller_shipment import SellerShipment, SellerShipmentLine
from src.models.seller_user import SellerUser
from src.services.local_carrier_simulator import LocalCarrierSimulator


@pytest.mark.postgres_integration
def test_live_local_carrier_recovers_label_after_lost_ack_without_duplicate() -> None:
    database_url = os.getenv("NEOMARKET_POSTGRES_TEST_URL")
    if not database_url:
        pytest.skip("set PostgreSQL URL for seller carrier reconciliation integration")

    async def scenario() -> None:
        engine = create_async_engine(database_url, poolclass=NullPool)
        sessions = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        seller_id, user_id, order_id, order_item_id, shipment_id = (uuid4() for _ in range(5))
        email = f"seller-carrier-{uuid4()}@example.com"
        password = "DisposableCarrier!2026"
        idem_key = uuid4()
        try:
            async with sessions() as session:
                digest = hash_password(password)
                now = datetime.now(timezone.utc)
                seller = Seller(id=seller_id, email=email, hashed_password=digest, company_name="Carrier simulation fixture", is_active=True, account_status="ACTIVE", email_verified_at=now)
                user = SellerUser(id=user_id, email=email, hashed_password=digest, is_active=True, email_verified_at=now)
                item = SellerOrderItem(id=order_item_id, sku_id=uuid4(), product_id=uuid4(), product_title="Carrier fixture", sku_name="Test parcel", quantity=1, unit_price_minor=500, line_total_minor=500)
                order = SellerOrder(id=order_id, buyer_order_id=uuid4(), seller_id=seller_id, currency="RUB", status="CREATED", total_minor=500, revision=2, allocated_at=now, seller_accepted_at=now, items=[item])
                shipment = SellerShipment(id=shipment_id, seller_order_id=order_id, seller_id=seller_id, idempotency_key=uuid4(), request_sha256="a" * 64, status="PACKED", packed_at=now, lines=[SellerShipmentLine(seller_order_item_id=order_item_id, quantity=1)])
                session.add_all([seller, user, order, shipment])
                await session.flush()
                session.add(SellerMembership(seller_id=seller_id, user_id=user_id, role="OWNER", active=True))
                await session.commit()

            async def unexpected_carrier_call(self, session, *, operation, shipment):
                raise AssertionError("disabled Seller dispatch must not call the carrier simulator")

            from pytest import MonkeyPatch

            monkeypatch = MonkeyPatch()
            monkeypatch.setattr(LocalCarrierSimulator, "create_label", unexpected_carrier_call)
            original_dependency = app.dependency_overrides.get(get_db)

            async def override_get_db():
                async with sessions() as session:
                    yield session

            app.dependency_overrides[get_db] = override_get_db
            try:
                client = TestClient(app)
                login = client.post("/auth/login", data={"username": email, "password": password})
                assert login.status_code == 200, login.text
                headers = {
                    "Authorization": f"Bearer {login.json()['access_token']}",
                    "Idempotency-Key": str(idem_key),
                }
                path = f"/api/v1/seller/orders/{order_id}/shipments/{shipment_id}/dispatch"
                first = client.post(path, headers=headers)
                assert first.status_code == 503, first.text
                assert first.json()["detail"]["code"] == "COMMERCIAL_FLOW_DISABLED"
                assert first.json()["detail"]["flow"] == "seller_carrier_dispatch"

                status_path = f"/api/v1/seller/orders/{order_id}/shipments/{shipment_id}/carrier-operation"
                repeated = client.post(path, headers=headers)
                assert repeated.status_code == 503, repeated.text
                assert repeated.json()["detail"]["code"] == "COMMERCIAL_FLOW_DISABLED"

                status_pending = client.get(status_path, headers=headers)
                assert status_pending.status_code == 404, status_pending.text

            finally:
                if original_dependency is None:
                    app.dependency_overrides.pop(get_db, None)
                else:
                    app.dependency_overrides[get_db] = original_dependency
                monkeypatch.undo()

            async with sessions() as session:
                labels = await session.scalar(
                    select(func.count())
                    .select_from(LocalCarrierLabel)
                    .where(LocalCarrierLabel.shipment_id == shipment_id)
                )
                assert labels == 0
                operation = await session.scalar(
                    select(SellerCarrierOperation).where(SellerCarrierOperation.shipment_id == shipment_id)
                )
                assert operation is None
        finally:
            async with sessions() as session:
                await session.execute(delete(LocalCarrierLabel).where(LocalCarrierLabel.shipment_id == shipment_id))
                await session.execute(delete(SellerCarrierOperation).where(SellerCarrierOperation.shipment_id == shipment_id))
                await session.execute(delete(SellerShipmentLine).where(SellerShipmentLine.shipment_id == shipment_id))
                await session.execute(delete(SellerShipment).where(SellerShipment.id == shipment_id))
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
