import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.api.routers import admin_internal
from src.core.config import settings
from src.models.seller import Seller


@pytest.mark.postgres_integration
def test_live_admin_seller_registry_and_restriction() -> None:
    database_url = os.getenv("NEOMARKET_ADMIN_INTERNAL_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("set NEOMARKET_ADMIN_INTERNAL_TEST_DATABASE_URL to a disposable PostgreSQL database")

    async def scenario() -> None:
        engine = create_async_engine(database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        seller_id = uuid4()
        second_seller_id = uuid4()

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
                session.add(Seller(
                    id=seller_id,
                    email=f"admin-seller-{seller_id}@example.com",
                    hashed_password="disposable-fixture-unused",
                    company_name="Disposable seller registry fixture",
                    is_active=True,
                    account_status="PENDING_REVIEW",
                    session_version=1,
                ))
                session.add(Seller(
                    id=second_seller_id,
                    email=f"admin-seller-{second_seller_id}@example.com",
                    hashed_password="disposable-fixture-unused",
                    company_name="Disposable seller registry fixture 2",
                    is_active=True,
                    account_status="PENDING_REVIEW",
                    session_version=1,
                ))
                await session.commit()
            async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
                page = await client.get("/internal/v1/sellers?limit=1", headers=headers)
                next_page = await client.get(
                    f"/internal/v1/sellers?limit=1&cursor={page.json()['page']['next_cursor']}",
                    headers=headers,
                )
                invalid_cursor = await client.get(
                    "/internal/v1/sellers?limit=1&cursor=not-a-cursor",
                    headers=headers,
                )
                case = await client.get(f"/internal/v1/sellers/{seller_id}", headers=headers)
                command_id = str(uuid4())
                command_payload = {
                    "command_id": command_id,
                    "command_type": "SELLER_RESTRICTION",
                    "aggregate_id": str(seller_id),
                    "expected_version": 1,
                    "payload": {
                        "action": "SUSPEND",
                        "reason_code": "COMPLIANCE_REVIEW",
                        "comment": "Disposable fixture",
                        "effective_until": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                    },
                }
                command = await client.post(
                    f"/internal/v1/sellers/{seller_id}/restrictions",
                    headers={**headers, "If-Match": '"1"'},
                    json=command_payload,
                )
                replay = await client.post(
                    f"/internal/v1/sellers/{seller_id}/restrictions",
                    headers={**headers, "If-Match": '"1"'},
                    json=command_payload,
                )
                conflict_payload = {
                    **command_payload,
                    "payload": {**command_payload["payload"], "reason_code": "DIFFERENT_REASON"},
                }
                conflict = await client.post(
                    f"/internal/v1/sellers/{seller_id}/restrictions",
                    headers={**headers, "If-Match": '"1"'},
                    json=conflict_payload,
                )
                stale = await client.post(
                    f"/internal/v1/sellers/{seller_id}/restrictions",
                    headers={**headers, "If-Match": '"1"'},
                    json={
                        "command_id": str(uuid4()),
                        "command_type": "SELLER_RESTRICTION",
                        "aggregate_id": str(seller_id),
                        "expected_version": 1,
                        "payload": {"action": "REINSTATE", "reason_code": "REVIEW_COMPLETE"},
                    },
                )
                restored = await client.post(
                    f"/internal/v1/sellers/{seller_id}/restrictions",
                    headers={**headers, "If-Match": '"2"'},
                    json={
                        "command_id": str(uuid4()),
                        "command_type": "SELLER_RESTRICTION",
                        "aggregate_id": str(seller_id),
                        "expected_version": 2,
                        "payload": {"action": "REINSTATE", "reason_code": "REVIEW_COMPLETE"},
                    },
                )
            assert page.status_code == 200, page.text
            assert page.json()["page"]["has_more"] is True
            assert page.json()["page"]["next_cursor"]
            assert next_page.status_code == 200, next_page.text
            assert next_page.json()["items"]
            seen_ids = {item["seller_id"] for item in page.json()["items"] + next_page.json()["items"]}
            assert {str(seller_id), str(second_seller_id)}.issubset(seen_ids)
            assert invalid_cursor.status_code == 422, invalid_cursor.text
            assert invalid_cursor.json()["detail"]["code"] == "INVALID_CURSOR"
            assert case.status_code == 200, case.text
            assert case.json()["version"] == 1
            assert command.status_code == 202, command.text
            assert command.json()["status"] == "APPLIED"
            assert replay.status_code == 202, replay.text
            assert replay.json() == command.json()
            assert conflict.status_code == 409, conflict.text
            assert conflict.json()["detail"]["code"] == "SELLER_COMMAND_ID_CONFLICT"
            assert stale.status_code == 412, stale.text
            assert restored.status_code == 202, restored.text
            assert restored.json()["result"]["status"] == "ACTIVE"
        finally:
            settings.app_env = previous_app_env
            async with sessions() as session:
                for fixture_id in (seller_id, second_seller_id):
                    seller = await session.get(Seller, fixture_id)
                    if seller is not None:
                        await session.delete(seller)
                    await session.commit()
            await engine.dispose()

    import asyncio

    asyncio.run(scenario())
