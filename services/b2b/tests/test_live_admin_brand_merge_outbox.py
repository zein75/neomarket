import asyncio
import os
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.api.routers import admin_internal
from src.core.config import settings
from src.models.brand import Brand, BrandMergeHistory, BrandMergePreview
from src.models.outbox_event import OutboxEvent
from src.models.product import Product
from src.models.seller import Seller
from src.models.taxonomy_command_receipt import TaxonomyCommandReceipt
from src.models.taxonomy_state import TaxonomyState


@pytest.mark.postgres_integration
def test_brand_merge_and_b2c_event_commit_once() -> None:
    database_url = os.getenv("NEOMARKET_ADMIN_INTERNAL_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("set NEOMARKET_ADMIN_INTERNAL_TEST_DATABASE_URL to a disposable PostgreSQL database")

    async def scenario() -> None:
        engine = create_async_engine(database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        source_id, target_id, seller_id, product_id = (uuid4() for _ in range(4))
        preview_id, command_id, invalid_command_id = uuid4(), uuid4(), uuid4()
        async with sessions() as session:
            state = await session.get(TaxonomyState, 1)
            assert state is not None
            initial_taxonomy_version = state.version
            session.add_all(
                [
                    Seller(
                        id=seller_id,
                        email=f"{seller_id.hex}@example.invalid",
                        hashed_password="test-only",
                        company_name="Brand merge fixture",
                        is_active=True,
                    ),
                    Brand(
                        id=source_id,
                        name="Legacy fixture brand",
                        normalized_name=f"legacy-{source_id.hex}",
                        status="DRAFT",
                        version=1,
                    ),
                    Brand(
                        id=target_id,
                        name="Canonical fixture brand",
                        normalized_name=f"canonical-{target_id.hex}",
                        status="VERIFIED",
                        evidence_ref="fixture:approved-brand-record",
                        version=1,
                    ),
                    Product(
                        id=product_id,
                        seller_id=seller_id,
                        title="Brand merge fixture product",
                        brand_id=source_id,
                        is_active=False,
                        status="CREATED",
                    ),
                ]
            )
            await session.commit()

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
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://testserver"
            ) as client:
                preview = await client.post(
                    f"/internal/v1/taxonomy/brands/{source_id}/merge-preview",
                    json={"target_brand_id": str(target_id)},
                    headers={
                        **headers,
                        "Idempotency-Key": str(preview_id),
                        "If-Match": '"1"',
                    },
                )
                assert preview.status_code == 200, preview.text
                assert preview.json()["affected_products"] == 1

                command = {
                    "command_id": str(command_id),
                    "command_type": "BRAND_MERGE",
                    "aggregate_id": str(source_id),
                    "expected_version": 1,
                    "impact_hash": preview.json()["hash"],
                    "payload": {
                        "target_brand_id": str(target_id),
                        "impact_hash": preview.json()["hash"],
                        "reason_code": "DUPLICATE_BRAND_RECORD",
                    },
                    "requested_by_staff_id": str(uuid4()),
                    "approved_by_staff_id": str(uuid4()),
                    "reason_code": "DUPLICATE_BRAND_RECORD",
                    "occurred_at": datetime.now(timezone.utc).isoformat(),
                }
                mismatched_reason = await client.post(
                    "/internal/v1/taxonomy/commands",
                    json={
                        **command,
                        "command_id": str(invalid_command_id),
                        "reason_code": "DIFFERENT_REASON",
                    },
                    headers={
                        **headers,
                        "Idempotency-Key": str(invalid_command_id),
                        "If-Match": '"1"',
                    },
                )
                assert mismatched_reason.status_code == 200, mismatched_reason.text
                assert mismatched_reason.json()["status"] == "REJECTED"
                assert mismatched_reason.json()["result"]["code"] == "BRAND_REASON_CODE_MISMATCH"
                response = await client.post(
                    "/internal/v1/taxonomy/commands",
                    json=command,
                    headers={
                        **headers,
                        "Idempotency-Key": str(command_id),
                        "If-Match": '"1"',
                    },
                )
                assert response.status_code == 200, response.text
                assert response.json()["status"] == "APPLIED"
                replay = await client.post(
                    "/internal/v1/taxonomy/commands",
                    json=command,
                    headers={
                        **headers,
                        "Idempotency-Key": str(command_id),
                        "If-Match": '"1"',
                    },
                )
                assert replay.status_code == 200, replay.text
                assert replay.json() == response.json()

            async with sessions() as session:
                events = list(
                    (
                        await session.scalars(
                            select(OutboxEvent).where(
                                OutboxEvent.idempotency_key
                                == f"brand-merged:{command_id}"
                            )
                        )
                    ).all()
                )
                assert len(events) == 1
                event = events[0]
                assert event.destination == "B2C"
                assert event.event_type == "brand.merged.v1"
                assert event.status == "PENDING"
                assert event.payload["aggregate_type"] == "brand"
                assert event.payload["aggregate_id"] == str(source_id)
                assert event.payload["payload"]["target_brand_id"] == str(target_id)
                product = await session.get(Product, product_id)
                source = await session.get(Brand, source_id)
                target = await session.get(Brand, target_id)
                state = await session.get(TaxonomyState, 1)
                assert product is not None and product.brand_id == target_id
                assert source is not None and source.status == "MERGED"
                assert target is not None and target.version == 2
                assert state is not None and state.version == initial_taxonomy_version + 1
        finally:
            settings.app_env = previous_app_env
            async with sessions() as session:
                await session.execute(
                    delete(OutboxEvent).where(
                        OutboxEvent.idempotency_key == f"brand-merged:{command_id}"
                    )
                )
                await session.execute(
                    delete(TaxonomyCommandReceipt).where(
                        TaxonomyCommandReceipt.command_id.in_([command_id, invalid_command_id])
                    )
                )
                await session.execute(
                    delete(BrandMergeHistory).where(
                        BrandMergeHistory.command_id == command_id
                    )
                )
                await session.execute(
                    delete(BrandMergePreview).where(BrandMergePreview.id == preview_id)
                )
                await session.execute(delete(Product).where(Product.id == product_id))
                await session.execute(delete(Brand).where(Brand.id.in_([source_id, target_id])))
                await session.execute(delete(Seller).where(Seller.id == seller_id))
                state = await session.get(TaxonomyState, 1)
                if state is not None:
                    state.version = initial_taxonomy_version
                await session.commit()
            await engine.dispose()

    asyncio.run(scenario())
