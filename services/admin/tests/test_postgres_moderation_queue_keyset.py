"""Admin moderation queue filtering and cursor ordering on PostgreSQL."""

import os
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from src.api.routers.moderation import list_tickets
from src.models.moderation import ModerationCard, ModerationStatus

pytestmark = pytest.mark.postgres_integration


def _database_url() -> str:
    url = os.getenv("NEOMARKET_ADMIN_POSTGRES_TEST_URL")
    if not url:
        pytest.skip("set NEOMARKET_ADMIN_POSTGRES_TEST_URL to run Admin PostgreSQL integration tests")
    if "+asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


async def _page(engine, *, cursor: str | None = None, limit: int = 2, **filters):
    actor = SimpleNamespace(
        id=uuid4(), permissions={"*"}, permission_scopes={}
    )
    async with AsyncSession(engine) as session:
        return await list_tickets(
            cursor=cursor,
            limit=limit,
            status_filter=filters.get("status_filter"),
            priority=filters.get("priority"),
            seller_id=filters.get("seller_id"),
            current_moderator=actor,
            db=session,
        )


@pytest.mark.asyncio
async def test_postgres_queue_keyset_is_stable_and_does_not_duplicate_tickets() -> None:
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    try:
        created_at = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
        ticket_ids = [UUID(int=value) for value in range(100, 105)]
        seller_id = uuid4()
        async with AsyncSession(engine) as session, session.begin():
            session.add_all(
                ModerationCard(
                    id=ticket_id,
                    product_id=uuid4(),
                    seller_id=seller_id,
                    kind="CREATE",
                    status=ModerationStatus.PENDING,
                    queue_priority=4,
                    submitted_revision=1,
                    snapshot_hash=f"{value:064x}",
                    version=1,
                    fencing_version=0,
                    created_at=created_at,
                    updated_at=created_at,
                )
                for value, ticket_id in enumerate(ticket_ids, start=1)
            )

        seen: list[UUID] = []
        cursor = None
        while True:
            page = await _page(engine, cursor=cursor, limit=2, seller_id=seller_id)
            seen.extend(item.id for item in page["items"])
            if not page["page"]["has_more"]:
                break
            cursor = page["page"]["next_cursor"]
            assert cursor

        assert seen == ticket_ids
        assert len(seen) == len(set(seen))
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_queue_applies_status_priority_and_seller_filters() -> None:
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    try:
        seller_id, other_seller_id = uuid4(), uuid4()
        expected_id = uuid4()
        created_at = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
        rows = [
            (expected_id, seller_id, ModerationStatus.PENDING, 4),
            (uuid4(), seller_id, ModerationStatus.CREATED, 4),
            (uuid4(), other_seller_id, ModerationStatus.PENDING, 4),
            (uuid4(), seller_id, ModerationStatus.PENDING, 2),
        ]
        async with AsyncSession(engine) as session, session.begin():
            session.add_all(
                ModerationCard(
                    id=ticket_id,
                    product_id=uuid4(),
                    seller_id=row_seller_id,
                    kind="CREATE",
                    status=status,
                    queue_priority=priority,
                    submitted_revision=1,
                    snapshot_hash="a" * 64,
                    version=1,
                    fencing_version=0,
                    created_at=created_at,
                    updated_at=created_at,
                )
                for ticket_id, row_seller_id, status, priority in rows
            )

        page = await _page(
            engine,
            limit=10,
            status_filter=ModerationStatus.PENDING,
            priority=4,
            seller_id=seller_id,
        )
        assert [item.id for item in page["items"]] == [expected_id]
        assert page["page"]["has_more"] is False
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_queue_read_observes_a_new_ticket_after_insert() -> None:
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    try:
        first_id = uuid4()
        second_id = uuid4()
        assigned_id = uuid4()
        seller_id = uuid4()
        assigned_moderator = uuid4()
        created_at = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
        async with AsyncSession(engine) as session, session.begin():
            session.add(ModerationCard(
                id=first_id,
                product_id=uuid4(),
                seller_id=seller_id,
                kind="CREATE",
                status=ModerationStatus.PENDING,
                queue_priority=3,
                submitted_revision=1,
                snapshot_hash="a" * 64,
                version=1,
                fencing_version=0,
                created_at=created_at,
                updated_at=created_at,
            ))

        initial = await _page(engine, limit=10, seller_id=seller_id)
        assert [item.id for item in initial["items"]] == [first_id]

        async with AsyncSession(engine) as session, session.begin():
            session.add(ModerationCard(
                id=second_id,
                product_id=uuid4(),
                seller_id=seller_id,
                kind="CREATE",
                status=ModerationStatus.PENDING,
                queue_priority=5,
                submitted_revision=1,
                snapshot_hash="b" * 64,
                version=1,
                fencing_version=0,
                created_at=created_at,
                updated_at=created_at,
            ))
            session.add(ModerationCard(
                id=assigned_id,
                product_id=uuid4(),
                seller_id=seller_id,
                moderator_id=assigned_moderator,
                kind="CREATE",
                status=ModerationStatus.IN_REVIEW,
                queue_priority=4,
                submitted_revision=1,
                snapshot_hash="c" * 64,
                version=1,
                fencing_version=1,
                created_at=created_at,
                updated_at=created_at,
            ))

        refreshed = await _page(engine, limit=10, seller_id=seller_id)
        assert [item.id for item in refreshed["items"]] == [second_id, assigned_id, first_id]
        assigned_item = next(item for item in refreshed["items"] if item.id == assigned_id)
        assert assigned_item.assigned_to == assigned_moderator
        assert next(item for item in refreshed["items"] if item.id == first_id).assigned_to is None
    finally:
        await engine.dispose()
