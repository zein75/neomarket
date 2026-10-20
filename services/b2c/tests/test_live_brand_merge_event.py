import asyncio
import os
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.api.deps import get_db
from src.core.config import settings
from src.main import app
from src.models.processed_event import ProcessedB2BEvent


@pytest.mark.postgres_integration
def test_brand_merge_event_receipt_is_hash_bound_and_idempotent() -> None:
    database_url = os.getenv("NEOMARKET_B2B_EVENT_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("set NEOMARKET_B2B_EVENT_TEST_DATABASE_URL to a disposable PostgreSQL database")

    async def scenario() -> None:
        engine = create_async_engine(database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        source_id, target_id, event_id, correlation_id = (uuid4() for _ in range(4))

        async def db_override():
            async with sessions() as session:
                yield session

        app.dependency_overrides[get_db] = db_override
        previous_app_env = settings.app_env
        settings.app_env = "development"
        event = {
            "schema_version": 1,
            "event_id": str(event_id),
            "event_type": "brand.merged.v1",
            "producer": "b2b",
            "aggregate_type": "brand",
            "aggregate_id": str(source_id),
            "aggregate_version": 2,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "correlation_id": str(correlation_id),
            "causation_id": str(correlation_id),
            "payload": {
                "source_brand_id": str(source_id),
                "target_brand_id": str(target_id),
                "source_version": 2,
                "target_version": 4,
                "taxonomy_version": 11,
                "product_references_moved": 3,
                "impact_hash": "b" * 64,
            },
        }
        headers = {"X-Service-Key": settings.service_key}
        try:
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://testserver"
            ) as client:
                accepted = await client.post(
                    "/internal/v1/events/taxonomy", headers=headers, json=event
                )
                assert accepted.status_code == 202, accepted.text
                assert accepted.json() == {"accepted": True}

                replay = await client.post(
                    "/internal/v1/events/taxonomy", headers=headers, json=event
                )
                assert replay.status_code == 200, replay.text
                assert replay.json() == {"accepted": False}

                conflict = await client.post(
                    "/internal/v1/events/taxonomy",
                    headers=headers,
                    json={
                        **event,
                        "payload": {**event["payload"], "target_version": 5},
                    },
                )
                assert conflict.status_code == 409, conflict.text

            async with sessions() as session:
                receipt = await session.get(ProcessedB2BEvent, event_id)
                assert receipt is not None
                assert receipt.event == "brand.merged.v1"
                assert receipt.payload_hash
                count = await session.scalar(
                    select(func.count()).select_from(ProcessedB2BEvent).where(
                        ProcessedB2BEvent.idempotency_key == event_id
                    )
                )
                assert count == 1
        finally:
            settings.app_env = previous_app_env
            app.dependency_overrides.pop(get_db, None)
            async with sessions() as session:
                await session.execute(
                    delete(ProcessedB2BEvent).where(
                        ProcessedB2BEvent.idempotency_key == event_id
                    )
                )
                await session.commit()
            await engine.dispose()

    asyncio.run(scenario())
