"""Outbox retry idempotency must bind to actor, event, action and payload."""

import asyncio
import hashlib
import os
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.requests import Request

from src.api.routers.operations import propose_outbox_retry
from src.models.admin_operation import AdminOperation
from src.models.audit_log import AuditLog
from src.models.moderation_outbox_event import ModerationOutboxEvent
from src.models.staff_principal import StaffPrincipal
from src.schemas.admin import ReasonAction

pytestmark = pytest.mark.postgres_integration


def _database_url() -> str:
    url = os.getenv("NEOMARKET_ADMIN_POSTGRES_TEST_URL")
    if not url:
        pytest.skip("set NEOMARKET_ADMIN_POSTGRES_TEST_URL to run Admin PostgreSQL integration tests")
    if "+asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


def _request(request_id: str) -> Request:
    request = Request(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "https",
            "path": "/admin/v1/operations/events/retry",
            "raw_path": b"/admin/v1/operations/events/retry",
            "query_string": b"",
            "headers": [],
            "server": ("admin.test", 443),
            "client": ("127.0.0.1", 12345),
            "root_path": "",
            "path_params": {},
        }
    )
    request.state.request_id = request_id
    return request


async def _seed_actor_and_events(engine, event_count: int = 1):
    actor_id = uuid4()
    event_ids = [uuid4() for _ in range(event_count)]
    async with AsyncSession(engine) as session, session.begin():
        session.add(
            StaffPrincipal(
                id=actor_id,
                oidc_issuer="https://issuer.test",
                oidc_subject=f"outbox-retry-{actor_id}",
                status="ACTIVE",
            )
        )
        session.add_all(
            ModerationOutboxEvent(
                id=event_id,
                idempotency_key=str(uuid4()),
                event_type="MODERATION_DECISION",
                payload={"product_id": str(uuid4())},
                status="DEAD",
                attempts=5,
                created_at=datetime.now(timezone.utc),
            )
            for event_id in event_ids
        )
    return actor_id, event_ids


@pytest.mark.asyncio
async def test_postgres_outbox_retry_replay_requires_same_type_target_and_payload() -> None:
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    try:
        actor_id, event_ids = await _seed_actor_and_events(engine, event_count=3)
        first_event, other_event, _ = event_ids
        request = _request(f"outbox-retry-{uuid4()}")
        key, other_key = uuid4(), uuid4()
        body = ReasonAction(reason_code="OPS_REPLAY", comment="Retry after diagnosis")
        async with AsyncSession(engine) as session, session.begin():
            session.add(
                AdminOperation(
                    id=uuid4(),
                    action="AUDIT_EXPORT",
                    entity_type="audit_export",
                    entity_id=uuid4(),
                    payload={"range": "one-day"},
                    status="APPLIED",
                    version=1,
                    idempotency_key=str(other_key),
                    request_hash=hashlib.sha256(b"audit-export").hexdigest(),
                    requested_by=actor_id,
                    reason_code="AUDIT_EXPORT",
                )
            )

        async with AsyncSession(engine, expire_on_commit=False) as session:
            first = await propose_outbox_retry(
                first_event, body, request, key, SimpleNamespace(id=actor_id), session
            )
        assert first.status == "WAITING_APPROVAL"

        async with AsyncSession(engine) as session:
            replay = await propose_outbox_retry(
                first_event, body, request, key, SimpleNamespace(id=actor_id), session
            )
        assert replay.operation_id == first.operation_id

        conflict_calls = [
            (other_event, body, key),
            (
                first_event,
                ReasonAction(reason_code="OPS_REPLAY", comment="Changed payload"),
                key,
            ),
            (first_event, body, other_key),
        ]
        for event_id, data, idempotency_key in conflict_calls:
            async with AsyncSession(engine) as session:
                with pytest.raises(HTTPException) as conflict:
                    await propose_outbox_retry(
                        event_id,
                        data,
                        request,
                        idempotency_key,
                        SimpleNamespace(id=actor_id),
                        session,
                    )
            assert conflict.value.status_code == 409
            assert conflict.value.detail["code"] == "IDEMPOTENCY_KEY_REUSED"

        async with AsyncSession(engine) as session:
            first_operation = await session.get(AdminOperation, first.operation_id)
            operation_count = await session.scalar(
                select(func.count())
                .select_from(AdminOperation)
                .where(
                    AdminOperation.requested_by == actor_id,
                    AdminOperation.idempotency_key == str(key),
                )
            )
        assert first_operation is not None
        assert first_operation.action == "OUTBOX_RETRY"
        assert first_operation.entity_type == "outbox_event"
        assert first_operation.entity_id == first_event
        assert operation_count == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_concurrent_outbox_retry_same_key_returns_one_operation() -> None:
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    try:
        actor_id, event_ids = await _seed_actor_and_events(engine)
        event_id, key = event_ids[0], uuid4()
        request = _request(f"outbox-retry-race-{uuid4()}")
        body = ReasonAction(reason_code="OPS_REPLAY", comment="Retry after diagnosis")
        barrier = asyncio.Barrier(2)

        async def invoke():
            async with AsyncSession(engine, expire_on_commit=False) as session:
                original_scalar = session.scalar
                first_operation_lookup = True

                async def synchronized_scalar(statement, *args, **kwargs):
                    nonlocal first_operation_lookup
                    result = await original_scalar(statement, *args, **kwargs)
                    if (
                        first_operation_lookup
                        and "admin_operations" in str(statement)
                    ):
                        first_operation_lookup = False
                        await barrier.wait()
                    return result

                session.scalar = synchronized_scalar
                response = await propose_outbox_retry(
                    event_id,
                    body,
                    request,
                    key,
                    SimpleNamespace(id=actor_id),
                    session,
                )
                return response.operation_id

        operation_ids = await asyncio.gather(invoke(), invoke())
        assert operation_ids[0] == operation_ids[1]
        async with AsyncSession(engine) as session:
            operation_count = await session.scalar(
                select(func.count())
                .select_from(AdminOperation)
                .where(
                    AdminOperation.requested_by == actor_id,
                    AdminOperation.idempotency_key == str(key),
                )
            )
            audit_count = await session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.entity_id == event_id,
                    AuditLog.action == "OUTBOX_RETRY_PROPOSED",
                )
            )
        assert operation_count == audit_count == 1
    finally:
        await engine.dispose()
