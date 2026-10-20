"""Admin rejection corrections remain visible through the seller product contract."""

import asyncio
import hashlib
import json
import os
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.api.routers import moderation_events, products
from src.core.config import settings
from src.models.outbox_event import OutboxEvent
from src.models.processed_event import ProcessedEvent
from src.models.product import Product
from src.models.product_version import ProductVersion
from src.models.seller import Seller
from src.services.moderation_event_service import ModerationEventService


@pytest.mark.postgres_integration
def test_live_admin_rejection_corrections_are_visible_to_seller() -> None:
    database_url = os.getenv("NEOMARKET_ADMIN_INTERNAL_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("set NEOMARKET_ADMIN_INTERNAL_TEST_DATABASE_URL to a disposable PostgreSQL database")

    async def scenario() -> None:
        engine = create_async_engine(database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        seller_id, product_id = uuid4(), uuid4()
        decision_id, correlation_id = uuid4(), uuid4()
        seller: Seller | None = None

        async def db_override():
            async with sessions() as session:
                yield session

        async def seller_override():
            assert seller is not None
            return seller

        app = FastAPI()
        app.include_router(moderation_events.router)
        app.include_router(products.router)
        app.dependency_overrides[moderation_events.get_db] = db_override
        app.dependency_overrides[products.get_db] = db_override
        app.dependency_overrides[products.get_seller_or_service] = seller_override
        headers = {"X-Service-Key": settings.service_key}
        previous_app_env = settings.app_env
        settings.app_env = "development"
        try:
            async with sessions() as session:
                seller = Seller(
                    id=seller_id,
                    email=f"admin-feedback-{seller_id.hex}@example.invalid",
                    hashed_password="not-used",
                    company_name="Admin feedback fixture",
                    is_active=True,
                    account_status="ACTIVE",
                )
                product = Product(
                    id=product_id,
                    seller_id=seller_id,
                    title="Needs correction",
                    description="Fixture description",
                    category="fixture",
                    images=[],
                    characteristics={},
                    status="ON_MODERATION",
                    is_active=False,
                    revision=1,
                )
                session.add_all([seller, product])
                await session.flush()
                await session.refresh(product, attribute_names=["skus"])
                snapshot = ModerationEventService(session)._snapshot(product)
                snapshot_hash = hashlib.sha256(
                    json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest()
                session.add(
                    ProductVersion(
                        product_id=product_id,
                        seller_id=seller_id,
                        revision=1,
                        status="ON_MODERATION",
                        snapshot=snapshot,
                        snapshot_hash=snapshot_hash,
                        is_published=False,
                    )
                )
                await session.commit()

            async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
                response = await client.post(
                    "/internal/v1/moderation/decisions",
                    headers={**headers, "Idempotency-Key": str(correlation_id), "If-Match": '"1"'},
                    json={
                        "decision_id": str(decision_id),
                        "product_id": str(product_id),
                        "seller_id": str(seller_id),
                        "submitted_revision": 1,
                        "snapshot_hash": snapshot_hash,
                        "policy_version": 1,
                        "action": "CHANGES_REQUESTED",
                        "reason_codes": ["TITLE_INVALID"],
                        "field_reports": [
                            {
                                "field_path": "title",
                                "reason_code": "TITLE_INVALID",
                                "comment": "Исправьте заголовок товара.",
                            }
                        ],
                        "correlation_id": str(correlation_id),
                    },
                )
                assert response.status_code == 202, response.text

                seller_response = await client.get(f"/api/v1/seller/products/{product_id}")
                assert seller_response.status_code == 200, seller_response.text
                seller_payload = seller_response.json()
                assert seller_payload["status"] == "BLOCKED"
                assert seller_payload["field_reports"] == [
                    {
                        "field_name": "title",
                        "field_path": None,
                        "reason_code": "TITLE_INVALID",
                        "sku_id": None,
                        "comment": "Исправьте заголовок товара.",
                    }
                ]
                assert seller_payload["moderator_comment"] == "Исправьте заголовок товара."

            async with sessions() as session:
                stored = await session.get(Product, product_id)
                assert stored is not None
                assert stored.field_reports[0]["field_name"] == "title"
                assert stored.status == "BLOCKED"
        finally:
            settings.app_env = previous_app_env
            async with sessions() as session:
                await session.execute(
                    delete(OutboxEvent).where(
                        OutboxEvent.idempotency_key.in_([
                            f"publication-result:{decision_id}",
                            str(correlation_id),
                        ])
                    )
                )
                await session.execute(
                    delete(ProcessedEvent).where(ProcessedEvent.idempotency_key == str(correlation_id))
                )
                await session.execute(delete(Product).where(Product.id == product_id))
                await session.execute(delete(Seller).where(Seller.id == seller_id))
                await session.commit()
            await engine.dispose()

    asyncio.run(scenario())
