"""Exercise the Admin seller-review BFF against a live B2B process."""

import asyncio
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import asyncpg
import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from shared.utils.request_id import RequestIdMiddleware

from src.api.routers import sellers as sellers_router
from src.models.admin_operation import AdminOperation
from src.models.audit_log import AuditLog
from src.models.staff_principal import StaffPrincipal


@pytest.mark.postgres_integration
def test_live_admin_seller_review_bff_and_b2b_restriction() -> None:
    admin_database_url = os.getenv("NEOMARKET_ADMIN_BFF_TEST_DATABASE_URL")
    b2b_database_url = os.getenv("NEOMARKET_ADMIN_BFF_TEST_B2B_DATABASE_URL")
    b2b_base_url = os.getenv("NEOMARKET_ADMIN_BFF_TEST_B2B_BASE_URL")
    service_key = os.getenv("NEOMARKET_ADMIN_BFF_TEST_SERVICE_KEY", "dev-service-key-change-in-production")
    if not admin_database_url or not b2b_database_url or not b2b_base_url:
        pytest.skip("set Admin/B2B disposable database URLs and B2B base URL")

    async def scenario() -> None:
        admin_engine = create_async_engine(admin_database_url, poolclass=None)
        admin_sessions = async_sessionmaker(admin_engine, expire_on_commit=False, class_=AsyncSession)
        b2b_pool = await asyncpg.create_pool(b2b_database_url.replace("postgresql+asyncpg://", "postgresql://", 1))
        seller_id, second_seller_id = uuid4(), uuid4()
        order_id, buyer_order_id = uuid4(), uuid4()
        actor_id = uuid4()

        async def admin_db_override():
            async with admin_sessions() as session:
                yield session

        actor = SimpleNamespace(
            id=actor_id,
            permissions={"seller.review.read", "seller.restrict"},
            permission_scopes={"seller.review.read": {"*"}, "seller.restrict": {f"seller:{seller_id}"}},
            roles={"seller_compliance"},
            step_up_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )

        async def actor_override():
            return actor

        app = FastAPI()
        app.add_middleware(RequestIdMiddleware)
        app.include_router(sellers_router.router)
        app.dependency_overrides[sellers_router.get_db] = admin_db_override

        def override_required_permissions(dependencies: list[object]) -> None:
            for dependency in dependencies:
                call = getattr(dependency, "call", None)
                if getattr(call, "required_permission", None):
                    app.dependency_overrides[call] = actor_override
                override_required_permissions(getattr(dependency, "dependencies", []))

        for route in app.routes:
            override_required_permissions(getattr(getattr(route, "dependant", None), "dependencies", []))

        try:
            async with admin_sessions() as session:
                session.add(
                    StaffPrincipal(
                        id=actor_id,
                        oidc_issuer="https://keycloak.local/realms/neomarket-admin",
                        oidc_subject=f"seller-bff-fixture-{actor_id}",
                    )
                )
                await session.commit()

            async with b2b_pool.acquire() as connection:
                await connection.execute(
                    """
                    INSERT INTO sellers (id, email, hashed_password, company_name, is_active, account_status, session_version)
                    VALUES ($1, $2, 'disposable', 'BFF seller fixture', TRUE, 'PENDING_REVIEW', 1),
                           ($3, $4, 'disposable', 'BFF seller fixture 2', TRUE, 'PENDING_REVIEW', 1)
                    """,
                    seller_id,
                    f"bff-{seller_id.hex}@example.invalid",
                    second_seller_id,
                    f"bff-{second_seller_id.hex}@example.invalid",
                )
                await connection.execute(
                    """
                    INSERT INTO seller_orders (id, buyer_order_id, seller_id, currency, status, total_minor, revision, allocated_at)
                    VALUES ($1, $2, $3, 'RUB', 'CREATED', 1999, 1, NOW())
                    """,
                    order_id,
                    buyer_order_id,
                    seller_id,
                )

            async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as admin_client:
                list_response = await admin_client.get("/admin/v1/sellers?limit=2")
                assert list_response.status_code == 200, list_response.text
                assert any(item["seller_id"] == str(seller_id) for item in list_response.json()["items"])

                detail_response = await admin_client.get(f"/admin/v1/sellers/{seller_id}")
                assert detail_response.status_code == 200, detail_response.text
                assert detail_response.json()["status"] == "UNDER_REVIEW"
                assert detail_response.json()["version"] == 1

                command_id = uuid4()
                proposal_response = await admin_client.post(
                    f"/admin/v1/sellers/{seller_id}/restrictions",
                    headers={"If-Match": '"1"', "Idempotency-Key": str(command_id)},
                    json={
                        "action": "SUSPEND",
                        "reason_code": "COMPLIANCE_REVIEW",
                        "comment": "Review required",
                        "effective_until": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                    },
                )
                assert proposal_response.status_code == 202, proposal_response.text
                operation_id = proposal_response.json()["operation_id"]

                history_response = await admin_client.get(f"/admin/v1/sellers/{seller_id}/history")
                assert history_response.status_code == 200, history_response.text
                assert any(item["action"] == "SELLER_RESTRICTION_PROPOSED" for item in history_response.json()["items"])

            async with admin_sessions() as session:
                operation = await session.get(AdminOperation, operation_id)
                assert operation is not None
                assert operation.status == "WAITING_APPROVAL"
                assert operation.reason_code == "COMPLIANCE_REVIEW"
                audit = await session.scalar(
                    select(AuditLog).where(
                        AuditLog.action == "SELLER_RESTRICTION_PROPOSED",
                        AuditLog.entity_id == seller_id,
                    )
                )
                assert audit is not None
                assert audit.details["reason_code"] == "COMPLIANCE_REVIEW"

            async with httpx.AsyncClient(base_url=b2b_base_url) as b2b_client:
                command_response = await b2b_client.post(
                    f"/internal/v1/sellers/{seller_id}/restrictions",
                    headers={"X-Service-Key": service_key, "If-Match": '"1"'},
                    json={
                        "command_id": str(uuid4()),
                        "command_type": "SELLER_RESTRICTION",
                        "aggregate_id": str(seller_id),
                        "expected_version": 1,
                        "payload": {
                            "action": "SUSPEND",
                            "reason_code": "COMPLIANCE_REVIEW",
                            "effective_until": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                        },
                    },
                )
                assert command_response.status_code == 200, command_response.text
                assert command_response.json()["result"]["status"] == "SUSPENDED"

            async with b2b_pool.acquire() as connection:
                seller_status = await connection.fetchrow(
                    "SELECT account_status, session_version FROM sellers WHERE id = $1", seller_id
                )
                order_status = await connection.fetchrow(
                    "SELECT status, seller_id FROM seller_orders WHERE id = $1", order_id
                )
                assert dict(seller_status) == {"account_status": "SUSPENDED", "session_version": 2}
                assert dict(order_status) == {"status": "CREATED", "seller_id": seller_id}
        finally:
            async with b2b_pool.acquire() as connection:
                await connection.execute("DELETE FROM seller_orders WHERE id = $1", order_id)
                await connection.execute("DELETE FROM sellers WHERE id = ANY($1::uuid[])", [seller_id, second_seller_id])
            await b2b_pool.close()
            await admin_engine.dispose()

    asyncio.run(scenario())
