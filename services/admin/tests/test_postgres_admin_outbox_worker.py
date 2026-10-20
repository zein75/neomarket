"""Admin outbox workers lease, resume, deduplicate, and dead-letter safely."""

import asyncio
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.requests import Request

from src.api.deps import require_permission
from src.models.audit_log import AuditLog
from src.models.admin_operation import AdminOperation
from src.models.moderation_outbox_event import ModerationOutboxEvent
from src.models.staff_principal import StaffPrincipal
from src.services import moderation_service
from src.services.moderation_service import ModerationService
from src.workers import outbox

pytestmark = pytest.mark.postgres_integration


def _database_url() -> str:
    url = os.getenv("NEOMARKET_ADMIN_POSTGRES_TEST_URL")
    if not url:
        pytest.skip("set NEOMARKET_ADMIN_POSTGRES_TEST_URL to run Admin PostgreSQL integration tests")
    return url.replace("postgresql://", "postgresql+asyncpg://", 1) if "+asyncpg" not in url else url


def _request() -> Request:
    path = "/admin/v1/operations/events/retry"
    request = Request({
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [],
        "server": ("admin.test", 443),
        "client": ("127.0.0.1", 12345),
        "root_path": "",
        "path_params": {},
    })
    request.state.request_id = str(uuid4())
    return request


def _event(*, status: str = "PENDING", attempts: int = 0, lease_until=None) -> ModerationOutboxEvent:
    return ModerationOutboxEvent(
        id=uuid4(),
        idempotency_key=f"worker-{uuid4()}",
        event_type="MODERATION_DECISION",
        payload={"decision_id": str(uuid4()), "product_id": str(uuid4())},
        status=status,
        attempts=attempts,
        lease_until=lease_until,
        created_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_postgres_outbox_claim_reclaims_expired_lease_and_two_workers_split_rows() -> None:
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    try:
        first, second = _event(), _event()
        first.created_at = datetime(2000, 1, 1, tzinfo=timezone.utc)
        second.created_at = first.created_at + timedelta(seconds=1)
        second_id = second.id
        async with AsyncSession(engine) as session, session.begin():
            session.add_all([first, second])

        async with AsyncSession(engine, expire_on_commit=False) as session:
            claimed = await ModerationService(session).claim_pending_decisions(
                worker_id="worker-a", limit=1, lease_seconds=60
            )
            assert len(claimed) == 1
            assert claimed[0].status == "LEASED"
            await session.commit()
            first_id = claimed[0].id

        async with AsyncSession(engine, expire_on_commit=False) as session:
            row = await session.get(ModerationOutboxEvent, first_id)
            assert row is not None
            row.lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
            await session.commit()

        async with AsyncSession(engine, expire_on_commit=False) as session:
            reclaimed = await ModerationService(session).claim_pending_decisions(
                worker_id="worker-b", limit=1, lease_seconds=60
            )
            assert [item.id for item in reclaimed] == [first_id]
            assert reclaimed[0].lease_owner == "worker-b"
            await session.commit()

        async with AsyncSession(engine, expire_on_commit=False) as left, AsyncSession(engine, expire_on_commit=False) as right:
            left_claim = await ModerationService(left).claim_pending_decisions(
                worker_id="worker-left", limit=1, lease_seconds=60
            )
            right_claim = await ModerationService(right).claim_pending_decisions(
                worker_id="worker-right", limit=1, lease_seconds=60
            )
            assert {item.id for item in left_claim + right_claim} == {second_id}
            assert len(left_claim) + len(right_claim) == 1
            await left.rollback()
            await right.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_outbox_retry_resumes_expired_lease_and_dead_letters_after_max_attempts(monkeypatch) -> None:
    class FakeB2BClient:
        async def send_moderation_decision(self, _payload):
            return {"status": "accepted"}

    monkeypatch.setattr(moderation_service, "B2BClient", FakeB2BClient)
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    try:
        resumable = _event(status="LEASED", lease_until=datetime.now(timezone.utc) - timedelta(seconds=1))
        dead = _event(status="PENDING", attempts=ModerationService.MAX_OUTBOX_ATTEMPTS)
        resumable_id, dead_id = resumable.id, dead.id
        async with AsyncSession(engine) as session, session.begin():
            session.add_all([resumable, dead])

        async with AsyncSession(engine, expire_on_commit=False) as session:
            delivered = await ModerationService(session).retry_pending_decisions(limit=10)
            # A moderation HTTP acknowledgement is not publication delivery;
            # it transitions to WAITING_ACK and remains pending for the durable
            # publication-result event.
            assert delivered == 0
            await session.commit()

        async with AsyncSession(engine) as session:
            resumed = await session.get(ModerationOutboxEvent, resumable_id)
            dead_row = await session.get(ModerationOutboxEvent, dead_id)
            assert resumed is not None and resumed.status == "WAITING_ACK"
            assert resumed.attempts == 1 and resumed.lease_owner is None
            assert dead_row is not None and dead_row.status == "DEAD"
            assert dead_row.last_error == "OUTBOX_MAX_ATTEMPTS_EXCEEDED"
            assert dead_row.attempts == ModerationService.MAX_OUTBOX_ATTEMPTS + 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_b2b_command_delivery_applies_operation_and_audits(monkeypatch) -> None:
    class FakeB2BClient:
        calls: list[dict[str, object]] = []

        async def submit_safety_command(self, command):
            type(self).calls.append(command)
            return {"command_id": command["command_id"], "status": "APPLIED"}

    monkeypatch.setattr(moderation_service, "B2BClient", FakeB2BClient)
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    operation_id = uuid4()
    seller_id = uuid4()
    command_id = uuid4()
    requester_id = uuid4()
    try:
        async with AsyncSession(engine) as session, session.begin():
            session.add(
                StaffPrincipal(
                    id=requester_id,
                    oidc_issuer="https://issuer.test",
                    oidc_subject=f"b2b-command-{requester_id}",
                    status="ACTIVE",
                )
            )
            await session.flush()
            command = {
                "command_id": str(command_id),
                "command_type": "SELLER_RESTRICTION",
                "aggregate_id": str(seller_id),
                "expected_version": 1,
                "payload": {
                    "action": "SUSPEND",
                    "reason_code": "COMPLIANCE_REVIEW",
                },
            }
            session.add(
                AdminOperation(
                    id=operation_id,
                    action="SELLER_RESTRICTION",
                    entity_type="seller",
                    entity_id=seller_id,
                    payload={"command": command},
                    status="QUEUED",
                    version=2,
                    idempotency_key=f"operation:{operation_id}",
                    request_hash="a" * 64,
                    requested_by=requester_id,
                    reason_code="COMPLIANCE_REVIEW",
                    updated_at=datetime.now(timezone.utc),
                )
            )
            session.add(
                ModerationOutboxEvent(
                    id=uuid4(),
                    idempotency_key=f"admin-command:{operation_id}",
                    event_type="B2B_COMMAND",
                    payload={
                        "operation_id": str(operation_id),
                        "entity_type": "seller",
                        "command": command,
                    },
                    status="PENDING",
                    attempts=0,
                    created_at=datetime.now(timezone.utc),
                )
            )

        async with AsyncSession(engine, expire_on_commit=False) as session:
            delivered = await ModerationService(session).retry_pending_decisions(limit=10)
            assert delivered == 1
            await session.commit()

        async with AsyncSession(engine) as session:
            operation = await session.get(AdminOperation, operation_id)
            event = await session.scalar(
                select(ModerationOutboxEvent).where(
                    ModerationOutboxEvent.idempotency_key == f"admin-command:{operation_id}"
                )
            )
            audit = await session.scalar(
                select(AuditLog)
                .where(
                    AuditLog.action == "ADMIN_COMMAND_APPLIED",
                    AuditLog.entity_id == seller_id,
                )
                .order_by(AuditLog.created_at.desc())
            )
            assert operation is not None and operation.status == "APPLIED"
            assert event is not None and event.status == "SENT" and event.attempts == 1
            assert audit is not None and audit.details["operation_id"] == str(operation_id)
            assert FakeB2BClient.calls == [command]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_outbox_worker_emits_dlq_alert_for_dead_events(monkeypatch, tmp_path) -> None:
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    try:
        async with AsyncSession(engine) as session, session.begin():
            session.add(_event(status="DEAD", attempts=ModerationService.MAX_OUTBOX_ATTEMPTS + 1))
            session.add(_event(status="RETRY", attempts=1))

        monkeypatch.setattr(outbox, "AsyncSessionLocal", lambda: AsyncSession(engine, expire_on_commit=False))
        monkeypatch.setattr(outbox, "_HEARTBEAT", tmp_path / "admin-worker.json")
        monkeypatch.setattr(outbox, "record_worker_metric", lambda *_args: None)
        errors: list[str] = []
        monkeypatch.setattr(outbox.logger, "error", lambda message, *args: errors.append(message % args if args else message))

        class IdleModerationService:
            def __init__(self, _db):
                pass

            async def retry_pending_decisions(self):
                return 0

        monkeypatch.setattr(outbox, "ModerationService", IdleModerationService)
        stop = asyncio.Event()

        async def stop_after_cycle(awaitable, *, timeout):
            stop.set()
            return await awaitable

        monkeypatch.setattr(outbox.asyncio, "wait_for", stop_after_cycle)
        await outbox.moderation_outbox_worker(stop)
        assert any("retry=" in message and "retry=0" not in message and "dead=" in message and "dead=0" not in message for message in errors), errors
        assert (tmp_path / "admin-worker.json").exists()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_manual_outbox_retry_requires_permission_and_audits_denial() -> None:
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    actor_id = uuid4()
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            actor = SimpleNamespace(id=actor_id, permissions={"operations.events.read"}, permission_scopes={})
            with pytest.raises(HTTPException) as denied:
                await require_permission("operations.events.retry")(_request(), actor, session)
            assert denied.value.status_code == 403
            await session.commit()

        async with AsyncSession(engine) as session:
            denial = await session.scalar(
                select(AuditLog).where(
                    AuditLog.actor_id.is_(None),
                    AuditLog.action == "ADMIN_ACCESS_DENIED",
                ).order_by(AuditLog.created_at.desc())
            )
            assert denial is not None
            assert denial.details["required_permission"] == "operations.events.retry"
    finally:
        await engine.dispose()
