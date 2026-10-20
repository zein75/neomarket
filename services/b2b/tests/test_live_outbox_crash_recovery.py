import asyncio
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.models.outbox_event import OutboxEvent
from src.repositories.outbox_event_repo import OutboxEventRepository
from src.services import reservation_service as reservation_service_module
from src.services.reservation_service import ReservationService


@pytest.mark.postgres_integration
def test_live_outbox_survives_worker_crash_after_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = os.getenv("NEOMARKET_POSTGRES_TEST_URL")
    if not database_url:
        pytest.skip("set NEOMARKET_POSTGRES_TEST_URL to an isolated migrated PostgreSQL database")

    event_id, idempotency_key = uuid4(), f"crash-recovery-{uuid4()}"
    payload = {
        "event_id": str(event_id),
        "event_type": "SKU_OUT_OF_STOCK",
        "schema_version": 1,
        "aggregate_type": "sku",
        "aggregate_id": str(uuid4()),
        "idempotency_key": idempotency_key,
        "occurred_at": "2026-10-19T00:00:00+00:00",
        "payload": {"sku_id": str(uuid4()), "product_id": str(uuid4())},
    }

    class RecoveringB2CClient:
        calls: list[dict[str, object]] = []

        async def send_outbox_event(self, event: dict[str, object]) -> None:
            self.calls.append(event)

    async def scenario() -> None:
        engine = create_async_engine(database_url, pool_pre_ping=True)
        sessions = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        try:
            # The producer transaction commits the durable outbox row. The worker
            # then crashes before making the downstream call; no publish occurs.
            async with sessions() as producer_session:
                await OutboxEventRepository(producer_session).create_b2c_event(
                    idempotency_key=idempotency_key,
                    event_type="SKU_OUT_OF_STOCK",
                    payload=payload,
                )
                await producer_session.commit()

            async with sessions() as inspection_session:
                committed = await inspection_session.scalar(
                    select(OutboxEvent).where(OutboxEvent.idempotency_key == idempotency_key)
                )
                assert committed is not None
                assert committed.status == "PENDING"
                assert RecoveringB2CClient.calls == []

            crash_worker = """
import asyncio
import os
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from src.repositories.outbox_event_repo import OutboxEventRepository

async def crash_after_claim() -> None:
    engine = create_async_engine(os.environ['NEOMARKET_POSTGRES_TEST_URL'])
    sessions = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with sessions() as session:
        events = await OutboxEventRepository(session).claim_pending(worker_id='crashed-worker', lease_seconds=60)
        assert len(events) == 1
        await session.commit()
    await engine.dispose()
    os._exit(23)

asyncio.run(crash_after_claim())
"""
            child_env = os.environ.copy()
            child_env["NEOMARKET_POSTGRES_TEST_URL"] = database_url
            crashed = subprocess.run(
                [sys.executable, "-c", crash_worker],
                cwd=os.path.dirname(os.path.dirname(__file__)),
                env=child_env,
                check=False,
            )
            assert crashed.returncode == 23

            async with sessions() as lease_session:
                leased = await lease_session.scalar(
                    select(OutboxEvent).where(OutboxEvent.idempotency_key == idempotency_key)
                )
                assert leased is not None
                assert leased.status == "LEASED"
                leased.lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
                await lease_session.commit()

            monkeypatch.setattr(reservation_service_module, "B2CClient", RecoveringB2CClient)
            async with sessions() as recovery_session:
                delivered = await ReservationService(recovery_session).retry_pending_outbox()
                await recovery_session.commit()
                assert delivered == 1

            async with sessions() as verification_session:
                recovered = await verification_session.scalar(
                    select(OutboxEvent).where(OutboxEvent.idempotency_key == idempotency_key)
                )
                assert recovered is not None
                assert recovered.status == "SENT"
                assert recovered.attempts == 1
                assert RecoveringB2CClient.calls == [payload]
        finally:
            async with sessions() as cleanup_session:
                event = await cleanup_session.scalar(
                    select(OutboxEvent).where(OutboxEvent.idempotency_key == idempotency_key)
                )
                if event is not None:
                    await cleanup_session.delete(event)
                    await cleanup_session.commit()
            await engine.dispose()

    asyncio.run(scenario())
