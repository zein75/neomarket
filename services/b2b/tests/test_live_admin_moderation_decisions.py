import asyncio
import hashlib
import json
import os
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from src.api.routers import moderation_events
from src.core.config import settings
from src.models.outbox_event import OutboxEvent
from src.models.product import Product
from src.models.product_moderation_history import ProductModerationHistory
from src.models.product_version import ProductVersion
from src.models.processed_event import ProcessedEvent
from src.models.seller import Seller
from src.models.sku import SKU
from src.services.moderation_event_service import ModerationEventService


@pytest.mark.postgres_integration
def test_live_admin_decision_returns_pending_and_emits_durable_result() -> None:
    database_url = os.getenv("NEOMARKET_ADMIN_INTERNAL_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("set NEOMARKET_ADMIN_INTERNAL_TEST_DATABASE_URL to a disposable PostgreSQL database")

    async def scenario() -> None:
        engine = create_async_engine(database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        seller_id = uuid4()
        product_ids = [uuid4(), uuid4()]
        sku_ids = [uuid4(), uuid4()]
        decision_ids = [uuid4(), uuid4(), uuid4()]
        correlation_ids = [uuid4(), uuid4(), uuid4()]
        product_hashes: list[str] = []

        async def db_override():
            async with sessions() as session:
                yield session

        app = FastAPI()
        app.include_router(moderation_events.router)
        app.dependency_overrides[moderation_events.get_db] = db_override
        headers = {"X-Service-Key": settings.service_key}
        previous_app_env = settings.app_env
        settings.app_env = "development"
        try:
            async with sessions() as session:
                session.add(
                    Seller(
                        id=seller_id,
                        email=f"admin-decision-{seller_id.hex}@example.invalid",
                        hashed_password="not-used",
                        company_name="Admin decision fixture",
                        is_active=True,
                        account_status="ACTIVE",
                    )
                )
                for index, (product_id, sku_id) in enumerate(zip(product_ids, sku_ids, strict=True)):
                    product = Product(
                        id=product_id,
                        seller_id=seller_id,
                        title="Reviewed title",
                        description="Reviewed description",
                        category="fixture",
                        images=[],
                        characteristics={},
                        status="ON_MODERATION",
                        is_active=False,
                        revision=1 if index == 0 else 2,
                    )
                    product.skus.append(
                        SKU(
                            id=sku_id,
                            name="Fixture SKU",
                            price=1000,
                            stock=3,
                            on_hand=3,
                            reserved_quantity=0,
                            images=[],
                            options={},
                            is_active=True,
                        )
                    )
                    session.add(product)
                await session.flush()
                for index, product_id in enumerate(product_ids):
                    product = await session.scalar(
                        select(Product)
                        .where(Product.id == product_id)
                        .options(selectinload(Product.skus))
                    )
                    assert product is not None
                    snapshot = ModerationEventService(session)._snapshot(product)
                    if index == 1:
                        product.title = "Newer seller revision"
                    digest = hashlib.sha256(
                        json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
                    ).hexdigest()
                    product_hashes.append(digest)
                    session.add(
                        ProductVersion(
                            product_id=product_id,
                            seller_id=seller_id,
                            revision=1,
                            status="ON_MODERATION",
                            snapshot=snapshot,
                            snapshot_hash=digest,
                            is_published=False,
                        )
                    )
                await session.commit()

            async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
                def command(index: int) -> dict[str, object]:
                    return {
                        "decision_id": str(decision_ids[index]),
                        "product_id": str(product_ids[index]),
                        "seller_id": str(seller_id),
                        "submitted_revision": 1,
                        "snapshot_hash": product_hashes[index],
                        "policy_version": 1,
                        "action": "APPROVE",
                        "reason_codes": [],
                        "field_reports": [],
                        "correlation_id": str(correlation_ids[index]),
                    }

                first_command = command(0)
                response = await client.post(
                    "/internal/v1/moderation/decisions",
                    json=first_command,
                    headers={
                        **headers,
                        "Idempotency-Key": str(correlation_ids[0]),
                        "If-Match": '"1"',
                    },
                )
                assert response.status_code == 202, response.text
                assert response.json() == {"command_id": str(decision_ids[0]), "status": "QUEUED"}

                replay = await client.post(
                    "/internal/v1/moderation/decisions",
                    json=first_command,
                    headers={
                        **headers,
                        "Idempotency-Key": str(correlation_ids[0]),
                        "If-Match": '"1"',
                    },
                )
                assert replay.status_code == 200, replay.text

                changed_replay = await client.post(
                    "/internal/v1/moderation/decisions",
                    json={**first_command, "action": "REJECT", "reason_codes": ["POLICY_REJECT"]},
                    headers={
                        **headers,
                        "Idempotency-Key": str(correlation_ids[0]),
                        "If-Match": '"1"',
                    },
                )
                assert changed_replay.status_code == 409, changed_replay.text
                assert changed_replay.json()["detail"]["code"] == "EVENT_ID_CONFLICT"

                async with sessions() as session:
                    approved_product = await session.get(Product, product_ids[0])
                    assert approved_product is not None
                    approved_product.revision = 2
                    await session.commit()
                out_of_order = {
                    **first_command,
                    "decision_id": str(decision_ids[2]),
                    "action": "REJECT",
                    "reason_codes": ["LATE_REJECT"],
                    "correlation_id": str(correlation_ids[2]),
                }
                out_of_order_response = await client.post(
                    "/internal/v1/moderation/decisions",
                    json=out_of_order,
                    headers={
                        **headers,
                        "Idempotency-Key": str(correlation_ids[2]),
                        "If-Match": '"1"',
                    },
                )
                assert out_of_order_response.status_code == 202, out_of_order_response.text

                stale_response = await client.post(
                    "/internal/v1/moderation/decisions",
                    json=command(1),
                    headers={
                        **headers,
                        "Idempotency-Key": str(correlation_ids[1]),
                        "If-Match": '"1"',
                    },
                )
                assert stale_response.status_code == 202, stale_response.text

            async with sessions() as session:
                approved = await session.get(Product, product_ids[0])
                assert approved is not None
                assert approved.status == "MODERATED"
                assert approved.published_revision == 1
                assert approved.revision == 2
                assert approved.is_active is True
                stale = await session.get(Product, product_ids[1])
                assert stale is not None
                assert stale.revision == 2
                assert stale.status == "ON_MODERATION"
                result_events = list(
                    (
                        await session.scalars(
                            select(OutboxEvent).where(
                                OutboxEvent.idempotency_key.in_(
                                    [f"publication-result:{item}" for item in decision_ids]
                                )
                            )
                        )
                    ).all()
                )
                assert len(result_events) == 3
                by_correlation = {str(row.correlation_id): row.payload for row in result_events}
                applied = by_correlation[str(correlation_ids[0])]
                assert applied["event_type"] == "product.publication.applied.v1"
                assert applied["aggregate_version"] == 1
                assert applied["payload"]["published_revision"] == 1
                assert applied["payload"]["visible"] is True
                rejected = by_correlation[str(correlation_ids[1])]
                assert rejected["event_type"] == "product.publication.rejected.v1"
                assert rejected["aggregate_version"] == 2
                assert rejected["payload"]["reason_code"] == "REVISION_CONFLICT"
                assert rejected["payload"]["visible"] is False
                out_of_order_result = by_correlation[str(correlation_ids[2])]
                assert out_of_order_result["event_type"] == "product.publication.rejected.v1"
                assert out_of_order_result["payload"]["reason_code"] == "REVISION_CONFLICT"
                assert out_of_order_result["payload"]["visible"] is True
                assert len({row.event_id for row in result_events}) == 3
                assert await session.scalar(
                    select(ProductModerationHistory.id).where(ProductModerationHistory.product_id == product_ids[0])
                ) is not None
        finally:
            settings.app_env = previous_app_env
            async with sessions() as session:
                await session.execute(
                    delete(OutboxEvent).where(
                        OutboxEvent.idempotency_key.in_(
                            [f"publication-result:{item}" for item in decision_ids]
                        )
                    )
                )
                await session.execute(
                    delete(ProcessedEvent).where(
                        ProcessedEvent.idempotency_key.in_([str(item) for item in correlation_ids])
                    )
                )
                await session.execute(delete(Product).where(Product.id.in_(product_ids)))
                await session.execute(delete(Seller).where(Seller.id == seller_id))
                await session.commit()
            await engine.dispose()

    asyncio.run(scenario())
