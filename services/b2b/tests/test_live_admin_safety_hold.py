import asyncio
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.api.routers import admin_internal
from src.core.config import settings
from src.models.category import Category
from src.models.outbox_event import OutboxEvent
from src.models.product import Product
from src.models.seller import Seller
from src.models.sku import SKU
from src.models.taxonomy_command_receipt import TaxonomyCommandReceipt


@pytest.mark.postgres_integration
def test_live_admin_product_safety_hold_is_transactional_and_replay_safe() -> None:
    database_url = os.getenv("NEOMARKET_ADMIN_INTERNAL_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("set NEOMARKET_ADMIN_INTERNAL_TEST_DATABASE_URL to a disposable PostgreSQL database")

    async def scenario() -> None:
        engine = create_async_engine(database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        seller_id, category_id, product_id, sku_id = uuid4(), uuid4(), uuid4(), uuid4()
        command_id, stale_command_id = uuid4(), uuid4()
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(hours=1)

        async def db_override():
            async with sessions() as session:
                yield session

        app = FastAPI()
        app.include_router(admin_internal.router)
        app.dependency_overrides[admin_internal.get_db] = db_override
        headers = {"X-Service-Key": settings.service_key}
        previous_app_env = settings.app_env
        settings.app_env = "development"
        try:
            async with sessions() as session:
                session.add_all(
                    [
                        Seller(
                            id=seller_id,
                            email=f"safety-hold-{product_id}@example.com",
                            hashed_password="unused-disposable-password",
                            company_name="Safety hold fixture",
                            is_active=True,
                            account_status="ACTIVE",
                            email_verified_at=now,
                        ),
                        Category(
                            id=category_id,
                            name="Safety hold fixture",
                            slug=f"safety-hold-{product_id}",
                            is_active=True,
                            revision=1,
                        ),
                        Product(
                            id=product_id,
                            seller_id=seller_id,
                            title="Safety hold fixture",
                            category_id=category_id,
                            images=[],
                            characteristics={},
                            status="MODERATED",
                            is_active=True,
                            deleted=False,
                            revision=4,
                            published_revision=4,
                        ),
                    ]
                )
                await session.flush()
                session.add(
                    SKU(
                        id=sku_id,
                        product_id=product_id,
                        name="Fixture SKU",
                        price=1000,
                        stock=2,
                        on_hand=2,
                        reserved_quantity=0,
                        images=[],
                        is_active=True,
                        revision=1,
                        options={},
                    )
                )
                await session.commit()

            command = {
                "command_id": str(command_id),
                "command_type": "PRODUCT_SAFETY_HOLD",
                "aggregate_id": str(product_id),
                "expected_version": 4,
                "payload": {
                    "reason_code": "RISK_REVIEW",
                    "expires_at": expires_at.isoformat(),
                    "comment": "Disposable safety hold fixture",
                },
                "requested_by_staff_id": str(uuid4()),
                "reason_code": "RISK_REVIEW",
                "occurred_at": now.isoformat(),
            }
            async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
                response = await client.post(
                    f"/internal/v1/products/{product_id}/safety-hold",
                    headers={**headers, "Idempotency-Key": str(command_id), "If-Match": '"4"'},
                    json=command,
                )
                replay = await client.post(
                    f"/internal/v1/products/{product_id}/safety-hold",
                    headers={**headers, "Idempotency-Key": str(command_id), "If-Match": '"4"'},
                    json=command,
                )
                conflict = await client.post(
                    f"/internal/v1/products/{product_id}/safety-hold",
                    headers={**headers, "Idempotency-Key": str(command_id), "If-Match": '"4"'},
                    json={**command, "payload": {**command["payload"], "reason_code": "OTHER_REASON"}},
                )
                stale = await client.post(
                    f"/internal/v1/products/{product_id}/safety-hold",
                    headers={**headers, "Idempotency-Key": str(stale_command_id), "If-Match": '"3"'},
                    json={**command, "command_id": str(stale_command_id), "expected_version": 3},
                )
                publication = await client.get(f"/internal/v1/products/{product_id}/publication", headers=headers)

            assert response.status_code == 202, response.text
            assert response.json()["status"] == "APPLIED"
            assert response.json()["aggregate_version"] == 4
            assert replay.status_code == 202, replay.text
            assert replay.json() == response.json()
            assert conflict.status_code == 409, conflict.text
            assert conflict.json()["detail"]["code"] == "PRODUCT_COMMAND_ID_CONFLICT"
            assert stale.status_code == 412, stale.text
            assert publication.status_code == 200, publication.text
            assert publication.json()["visible"] is False
            assert publication.json()["visibility_reasons"] == ["SAFETY_HOLD"]

            async with sessions() as session:
                product = await session.get(Product, product_id)
                assert product is not None
                product.safety_hold_until = now - timedelta(minutes=1)
                await session.commit()
            async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
                expired = await client.get(f"/internal/v1/products/{product_id}/publication", headers=headers)
            assert expired.status_code == 200, expired.text
            assert expired.json()["visible"] is True
            assert expired.json()["visibility_reasons"] == []

            async with sessions() as session:
                product = await session.get(Product, product_id)
                event = await session.scalar(select(OutboxEvent).where(OutboxEvent.idempotency_key == str(command_id)))
                receipt = await session.get(TaxonomyCommandReceipt, command_id)
                assert product is not None
                assert product.safety_hold_reason_code == "RISK_REVIEW"
                assert product.safety_hold_until is not None
                assert product.safety_hold_until < now
                assert event is not None
                assert event.event_type == "product.safety_hold.v1"
                assert event.payload["payload"]["product_id"] == str(product_id)
                assert receipt is not None
                assert receipt.status == "APPLIED"
        finally:
            settings.app_env = previous_app_env
            async with sessions() as session:
                await session.execute(delete(OutboxEvent).where(OutboxEvent.idempotency_key == str(command_id)))
                await session.execute(delete(TaxonomyCommandReceipt).where(TaxonomyCommandReceipt.command_id.in_([command_id, stale_command_id])))
                await session.execute(delete(SKU).where(SKU.id == sku_id))
                await session.execute(delete(Product).where(Product.id == product_id))
                await session.execute(delete(Category).where(Category.id == category_id))
                await session.execute(delete(Seller).where(Seller.id == seller_id))
                await session.commit()
            await engine.dispose()

    asyncio.run(scenario())
