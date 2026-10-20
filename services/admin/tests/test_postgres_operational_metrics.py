"""Operational dashboard and Prometheus metrics must reflect PostgreSQL rows."""

import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from src.api.routers.moderation import dashboard
from src.models.admin_operation import AdminOperation
from src.models.moderation import ModerationCard, ModerationStatus
from src.models.moderation_decision_receipt import ModerationDecisionReceipt
from src.models.moderation_outbox_event import ModerationOutboxEvent
from src.models.staff_principal import StaffPrincipal
from src.services.operational_metrics import render_operational_metrics

pytestmark = pytest.mark.postgres_integration


def _database_url() -> str:
    url = os.getenv("NEOMARKET_ADMIN_POSTGRES_TEST_URL")
    if not url:
        pytest.skip(
            "set NEOMARKET_ADMIN_POSTGRES_TEST_URL to run Admin PostgreSQL integration tests"
        )
    if "+asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


@pytest.mark.asyncio
async def test_postgres_dashboard_and_metrics_use_live_timestamped_data() -> None:
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    try:
        now = datetime.now(timezone.utc)
        ticket = ModerationCard(
            id=uuid4(),
            product_id=uuid4(),
            seller_id=uuid4(),
            kind="CREATE",
            status=ModerationStatus.PENDING,
            created_at=now - timedelta(seconds=120),
        )
        event = ModerationOutboxEvent(
            id=uuid4(),
            idempotency_key=f"metrics-{uuid4()}",
            event_type="MODERATION_DECISION",
            payload={"correlation_id": str(uuid4())},
            status="WAITING_ACK",
            created_at=now - timedelta(seconds=90),
        )

        async with AsyncSession(engine) as session, session.begin():
            before_pending = int(
                await session.scalar(
                    select(func.count())
                    .select_from(ModerationCard)
                    .where(
                        ModerationCard.status.in_(
                            (ModerationStatus.CREATED, ModerationStatus.PENDING)
                        )
                    )
                )
                or 0
            )
            before_pending_status = int(
                await session.scalar(
                    select(func.count())
                    .select_from(ModerationCard)
                    .where(ModerationCard.status == ModerationStatus.PENDING)
                )
                or 0
            )
            session.add_all((ticket, event))
            await session.flush()

            result = await dashboard(SimpleNamespace(), session)
            assert result["pending"] == before_pending + 1
            assert isinstance(result["as_of"], datetime)
            assert result["as_of"].tzinfo is not None
            assert now <= result["as_of"] <= datetime.now(timezone.utc)
            assert result["provenance"]["moderation"].startswith("moderation_cards.")
            assert result["provenance"]["outbox"].startswith(
                "moderation_outbox_events."
            )

            metrics = await render_operational_metrics(session)
            assert (
                f'admin_moderation_tickets{{status="PENDING"}} {before_pending_status + 1}'
                in metrics
            )
            assert 'admin_moderation_outbox_events{status="WAITING_ACK"}' in metrics
            assert "admin_moderation_outbox_oldest_waiting_ack_seconds " in metrics
            timestamp_line = next(
                line
                for line in metrics.splitlines()
                if line.startswith("admin_metrics_snapshot_timestamp_seconds ")
            )
            snapshot_timestamp = float(timestamp_line.rsplit(" ", 1)[1])
            assert (
                now.timestamp()
                <= snapshot_timestamp
                <= datetime.now(timezone.utc).timestamp()
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_dashboard_provenance_workload_and_resolution_average() -> None:
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    try:
        now = datetime.now(timezone.utc)
        actor_a, actor_b, resolver = uuid4(), uuid4(), uuid4()
        active_cards = [
            ModerationCard(
                id=uuid4(),
                product_id=uuid4(),
                seller_id=uuid4(),
                kind="CREATE",
                status=ModerationStatus.IN_REVIEW,
                moderator_id=actor_a,
                submitted_revision=1,
                snapshot_hash=f"{index:064x}",
                version=2,
                fencing_version=1,
                created_at=now - timedelta(minutes=index),
            )
            for index in (1, 2)
        ]
        active_cards.append(
            ModerationCard(
                id=uuid4(),
                product_id=uuid4(),
                seller_id=uuid4(),
                kind="CREATE",
                status=ModerationStatus.IN_REVIEW,
                moderator_id=actor_b,
                submitted_revision=1,
                snapshot_hash="b" * 64,
                version=2,
                fencing_version=1,
                created_at=now - timedelta(minutes=3),
            )
        )
        decision_cases = [
            ("APPROVE", "APPLIED", 60),
            ("REJECT", "FAILED", 120),
            ("ESCALATE", "APPLIED", 300),
            ("APPROVE", "RUNNING", 600),
        ]
        decision_cards = [
            ModerationCard(
                id=uuid4(),
                product_id=uuid4(),
                seller_id=uuid4(),
                kind="CREATE",
                status=ModerationStatus.DECISION_PENDING,
                submitted_revision=1,
                snapshot_hash=f"{index + 10:064x}",
                version=2,
                fencing_version=1,
                created_at=now - timedelta(minutes=10 + index),
            )
            for index in range(len(decision_cases))
        ]

        async with AsyncSession(engine) as session, session.begin():
            session.add_all(
                [
                    StaffPrincipal(
                        id=staff_id,
                        oidc_issuer="https://issuer.test",
                        oidc_subject=f"dashboard-{staff_id}",
                        status="ACTIVE",
                    )
                    for staff_id in (actor_a, actor_b, resolver)
                ]
            )
            await session.flush()
            baseline = await dashboard(SimpleNamespace(), session)
            session.add_all(active_cards + decision_cards)
            for index, ((action, status, duration), card) in enumerate(
                zip(decision_cases, decision_cards, strict=True)
            ):
                decision_id = uuid4()
                created_at = now - timedelta(hours=index + 1)
                updated_at = created_at + timedelta(seconds=duration)
                session.add_all(
                    [
                        ModerationDecisionReceipt(
                            id=decision_id,
                            ticket_id=card.id,
                            actor_id=resolver,
                            idempotency_key=f"dashboard-{uuid4()}",
                            request_hash=f"{index + 20:064x}",
                            action=action,
                            product_revision=1,
                            snapshot_hash=f"{index + 30:064x}",
                            policy_version=1,
                            reason_codes=[],
                            passed_rules=[],
                            field_reports=[],
                            result_status="DECISION_PENDING",
                        ),
                        AdminOperation(
                            id=decision_id,
                            action="MODERATION_DECISION",
                            entity_type="moderation_ticket",
                            entity_id=card.id,
                            payload={"action": action},
                            status=status,
                            version=2,
                            idempotency_key=f"dashboard-operation-{uuid4()}",
                            request_hash=f"{index + 40:064x}",
                            requested_by=resolver,
                            reason_code="DASHBOARD_TEST",
                            created_at=created_at,
                            updated_at=updated_at,
                        ),
                    ]
                )
            await session.flush()

            result = await dashboard(SimpleNamespace(), session)

        assert result["as_of"].tzinfo is not None
        assert set(result["provenance"]) >= {
            "moderation",
            "workload_by_moderator",
            "resolution_time",
            "complaints",
            "outbox",
        }
        assert result["provenance"]["workload_by_moderator"] == (
            "moderation_cards.moderator_id,status"
        )
        workload = {
            row["staff_id"]: row["in_review"]
            for row in result["workload_by_moderator"]
        }
        assert workload[actor_a] == 2
        assert workload[actor_b] == 1
        assert result["resolved_decision_count"] == baseline["resolved_decision_count"] + 2
        baseline_total = baseline["average_resolution_seconds"] or 0.0
        baseline_count = baseline["resolved_decision_count"]
        expected_average = (
            baseline_total * baseline_count + 60 + 120
        ) / (baseline_count + 2)
        assert result["average_resolution_seconds"] == pytest.approx(expected_average)
    finally:
        await engine.dispose()
