"""Admin claim locking and idempotency checks against a dedicated PostgreSQL DB."""

import asyncio
import os
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from src.models.audit_log import AuditLog
from src.models.admin_operation import AdminOperation
from src.models.moderation import ModerationCard, ModerationSKU, ModerationStatus
from src.models.moderation_claim_receipt import ModerationClaimReceipt
from src.models.moderation_decision_receipt import ModerationDecisionReceipt
from src.models.moderation_outbox_event import ModerationOutboxEvent
from src.models.moderation_snapshot import ModerationSnapshot
from src.models.staff_principal import StaffPrincipal
from src.services.moderation_service import ModerationService
from src.services.product_snapshots import content_digest

pytestmark = pytest.mark.postgres_integration


def _database_url() -> str:
    url = os.getenv("NEOMARKET_ADMIN_POSTGRES_TEST_URL")
    if not url:
        pytest.skip("set NEOMARKET_ADMIN_POSTGRES_TEST_URL to run Admin PostgreSQL integration tests")
    if "+asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


async def _seed_ticket(engine) -> tuple[ModerationCard, UUID]:
    ticket_id = uuid4()
    product_id = uuid4()
    content = {"product_id": str(product_id), "revision": 4, "policy_version": 1}
    snapshot_hash = "a" * 64
    card = ModerationCard(
        id=ticket_id,
        product_id=product_id,
        kind="CREATE",
        status=ModerationStatus.PENDING,
        submitted_revision=4,
        snapshot_hash=snapshot_hash,
        version=1,
        fencing_version=0,
    )
    async with AsyncSession(engine) as session, session.begin():
        session.add(card)
        session.add(
            ModerationSnapshot(
                ticket_id=ticket_id,
                revision=4,
                policy_version=1,
                snapshot_hash=snapshot_hash,
                content_hash=content_digest(content),
                content=content,
                media_refs=[],
            )
        )
    return card, ticket_id


async def _run_race(engine, calls, *, synchronize_initial_receipt_reads: bool = False):
    barrier = asyncio.Barrier(len(calls))
    receipt_barrier = asyncio.Barrier(len(calls)) if synchronize_initial_receipt_reads else None

    async def invoke(call):
        async with AsyncSession(engine, expire_on_commit=False) as session:
            if receipt_barrier is not None:
                scalar = session.scalar
                first_receipt_read = True

                async def synchronized_scalar(statement, *args, **kwargs):
                    nonlocal first_receipt_read
                    result = await scalar(statement, *args, **kwargs)
                    if first_receipt_read and "moderation_claim_receipts" in str(statement):
                        first_receipt_read = False
                        await receipt_barrier.wait()
                    return result

                session.scalar = synchronized_scalar
            await barrier.wait()
            try:
                result = await call(ModerationService(session))
                await session.commit()
                return ("ok", result)
            except HTTPException as exc:
                await session.rollback()
                return ("http", exc.status_code, exc.detail)

    return await asyncio.gather(*(invoke(call) for call in calls))


@pytest.mark.asyncio
async def test_postgres_concurrent_same_claim_key_replays_one_lease() -> None:
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    try:
        _, ticket_id = await _seed_ticket(engine)
        actor_id, key = uuid4(), uuid4()

        async def claim(service):
            return await service.claim_ticket(ticket_id, actor_id, idempotency_key=key)

        results = await _run_race(engine, [claim, claim], synchronize_initial_receipt_reads=True)
        assert [status for status, *_ in results] == ["ok", "ok"]
        assert results[0][1].claim_token == results[1][1].claim_token

        async with AsyncSession(engine) as session:
            card = await session.get(ModerationCard, ticket_id)
            receipt_count = await session.scalar(
                select(func.count()).select_from(ModerationClaimReceipt).where(
                    ModerationClaimReceipt.ticket_id == ticket_id
                )
            )
            audit_count = await session.scalar(
                select(func.count()).select_from(AuditLog).where(
                    AuditLog.entity_id == ticket_id,
                    AuditLog.action == "TICKET_CLAIM",
                )
            )
        assert card is not None
        assert card.moderator_id == actor_id
        assert card.version == 2
        assert card.fencing_version == 1
        assert receipt_count == 1
        assert audit_count == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_two_tabs_with_distinct_claim_keys_create_one_lease() -> None:
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    try:
        _, ticket_id = await _seed_ticket(engine)
        actor_id = uuid4()

        async def claim(service):
            return await service.claim_ticket(ticket_id, actor_id, idempotency_key=uuid4())

        results = await _run_race(engine, [claim, claim])
        assert sorted(result[0] for result in results) == ["http", "ok"]
        conflict = next(result for result in results if result[0] == "http")
        assert conflict[1] == 409
        assert conflict[2]["code"] == "CLAIM_NOT_ALLOWED"

        async with AsyncSession(engine) as session:
            card = await session.get(ModerationCard, ticket_id)
            receipt_count = await session.scalar(
                select(func.count()).select_from(ModerationClaimReceipt).where(
                    ModerationClaimReceipt.ticket_id == ticket_id
                )
            )
            audit_count = await session.scalar(
                select(func.count()).select_from(AuditLog).where(
                    AuditLog.entity_id == ticket_id,
                    AuditLog.action == "TICKET_CLAIM",
                )
            )
        assert card is not None and card.moderator_id == actor_id
        assert card.fencing_version == 1
        assert receipt_count == audit_count == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_two_moderators_cannot_claim_same_ticket() -> None:
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    try:
        _, ticket_id = await _seed_ticket(engine)
        actors = [uuid4(), uuid4()]

        async def claim(actor_id):
            async def call(service):
                return await service.claim_ticket(ticket_id, actor_id, idempotency_key=uuid4())

            return call

        results = await _run_race(engine, [await claim(actor) for actor in actors])
        assert sorted(result[0] for result in results) == ["http", "ok"]
        conflict = next(result for result in results if result[0] == "http")
        assert conflict[1] == 409
        assert conflict[2]["code"] == "TICKET_ALREADY_ASSIGNED"

        async with AsyncSession(engine) as session:
            card = await session.get(ModerationCard, ticket_id)
            receipt_count = await session.scalar(
                select(func.count()).select_from(ModerationClaimReceipt).where(
                    ModerationClaimReceipt.ticket_id == ticket_id
                )
            )
        assert card is not None
        assert card.moderator_id in actors
        assert card.fencing_version == 1
        assert receipt_count == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_current_lease_heartbeat_release_and_fencing() -> None:
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    try:
        _, ticket_id = await _seed_ticket(engine)
        original_actor, next_actor = uuid4(), uuid4()
        claim_key, heartbeat_key, release_key = uuid4(), uuid4(), uuid4()

        async with AsyncSession(engine, expire_on_commit=False) as session:
            claimed = await ModerationService(session).claim_ticket(
                ticket_id, original_actor, idempotency_key=claim_key
            )
            token = claimed.claim_token
            fencing_version = claimed.fencing_version
            version = claimed.version
            original_expiry = claimed.lease_expires_at
            assert original_expiry is not None
            await session.commit()

        async with AsyncSession(engine, expire_on_commit=False) as session:
            service = ModerationService(session)
            with pytest.raises(HTTPException) as wrong_token:
                await service.heartbeat_ticket(
                    ticket_id,
                    original_actor,
                    "wrong-token",
                    fencing_version=fencing_version,
                    expected_version=version,
                    idempotency_key=uuid4(),
                )
            assert wrong_token.value.status_code == 409

            renewed = await service.heartbeat_ticket(
                ticket_id,
                original_actor,
                token,
                fencing_version=fencing_version,
                expected_version=version,
                idempotency_key=heartbeat_key,
            )
            assert renewed.lease_expires_at > original_expiry
            assert renewed.version == version + 1
            await session.commit()

        async with AsyncSession(engine, expire_on_commit=False) as session:
            service = ModerationService(session)
            replay = await service.heartbeat_ticket(
                ticket_id,
                original_actor,
                token,
                fencing_version=fencing_version,
                expected_version=version,
                idempotency_key=heartbeat_key,
            )
            assert replay.version == version + 1
            released = await service.release_ticket(
                ticket_id,
                original_actor,
                token,
                fencing_version=fencing_version,
                expected_version=version + 1,
                idempotency_key=release_key,
            )
            assert released.status is ModerationStatus.PENDING
            assert released.moderator_id is None
            assert released.lease_token_hash is None
            assert released.lease_expires_at is None
            with pytest.raises(HTTPException) as released_token:
                await service.heartbeat_ticket(
                    ticket_id,
                    original_actor,
                    token,
                    fencing_version=fencing_version,
                    expected_version=version + 2,
                    idempotency_key=uuid4(),
                )
            assert released_token.value.status_code == 409
            assert released_token.value.detail["code"] == "TICKET_NOT_ASSIGNED"
            await session.commit()

        async with AsyncSession(engine, expire_on_commit=False) as session:
            reclaimed = await ModerationService(session).claim_ticket(
                ticket_id, original_actor, idempotency_key=uuid4()
            )
            old_fence = reclaimed.fencing_version
            await session.commit()
            stored = await session.get(ModerationCard, ticket_id)
            assert stored is not None
            stored.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            await session.commit()

        async with AsyncSession(engine, expire_on_commit=False) as session:
            new_owner_claim = await ModerationService(session).claim_ticket(
                ticket_id, next_actor, idempotency_key=uuid4()
            )
            assert new_owner_claim.moderator_id == next_actor
            assert new_owner_claim.fencing_version == old_fence + 1
            stale_version = new_owner_claim.version
            await session.commit()

        async with AsyncSession(engine, expire_on_commit=False) as session:
            with pytest.raises(HTTPException) as stale_client:
                await ModerationService(session).decide_ticket(
                    ticket_id,
                    original_actor,
                    idempotency_key=uuid4(),
                    expected_version=stale_version,
                    action="APPROVE",
                    claim_token=token,
                    product_revision=4,
                    snapshot_hash="a" * 64,
                    passed_rules=["PRODUCT_CONTENT_REVIEWED"],
                    policy_version=1,
                )
            assert stale_client.value.status_code == 409
            assert stale_client.value.detail["code"] == "TICKET_NOT_ASSIGNED"

        async with AsyncSession(engine) as session:
            card_row = await session.get(ModerationCard, ticket_id)
            receipt_count = await session.scalar(
                select(func.count())
                .select_from(ModerationClaimReceipt)
                .where(ModerationClaimReceipt.ticket_id == ticket_id)
            )
            heartbeat_count = await session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.entity_id == ticket_id,
                    AuditLog.action == "TICKET_HEARTBEAT",
                )
            )
            release_count = await session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.entity_id == ticket_id,
                    AuditLog.action == "TICKET_RELEASE",
                )
            )
        assert card_row is not None and card_row.moderator_id == next_actor
        assert card_row.fencing_version == 3
        assert receipt_count == 5
        assert heartbeat_count == 1 and release_count == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_decision_idempotency_hash_and_outbox_are_persisted_once() -> None:
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    try:
        _, ticket_id = await _seed_ticket(engine)
        actor_id, decision_key = uuid4(), uuid4()
        async with AsyncSession(engine) as session, session.begin():
            session.add(
                StaffPrincipal(
                    id=actor_id,
                    oidc_issuer="https://issuer.test",
                    oidc_subject=f"decision-idempotency-{actor_id}",
                    status="ACTIVE",
                )
            )
            session.add(
                ModerationSKU(
                    card_id=ticket_id, sku_id=uuid4(), name="Synthetic SKU"
                )
            )

        async with AsyncSession(engine, expire_on_commit=False) as session:
            claimed = await ModerationService(session).claim_ticket(
                ticket_id, actor_id, idempotency_key=uuid4()
            )
            claim_token = claimed.claim_token
            expected_version = claimed.version
            await session.commit()

        decision_arguments = {
            "idempotency_key": decision_key,
            "expected_version": expected_version,
            "action": "APPROVE",
            "claim_token": claim_token,
            "product_revision": 4,
            "snapshot_hash": "a" * 64,
            "passed_rules": ["PRODUCT_CONTENT_REVIEWED"],
            "policy_version": 1,
        }
        async with AsyncSession(engine, expire_on_commit=False) as session:
            first = await ModerationService(session).decide_ticket(
                ticket_id, actor_id, **decision_arguments
            )
            await session.commit()

        async with AsyncSession(engine, expire_on_commit=False) as session:
            replay = await ModerationService(session).decide_ticket(
                ticket_id, actor_id, **decision_arguments
            )
            assert replay.id == first.id
            with pytest.raises(HTTPException) as conflicting_replay:
                await ModerationService(session).decide_ticket(
                    ticket_id,
                    actor_id,
                    **{
                        **decision_arguments,
                        "comment": "changed payload under the same key",
                    },
                )
            assert conflicting_replay.value.status_code == 409
            assert conflicting_replay.value.detail["code"] == "IDEMPOTENCY_KEY_REUSED"

        async with AsyncSession(engine) as session:
            card_row = await session.get(ModerationCard, ticket_id)
            receipt = await session.get(ModerationDecisionReceipt, first.id)
            operation = await session.get(AdminOperation, first.id)
            outbox = await session.get(ModerationOutboxEvent, first.id)
            decision_count = await session.scalar(
                select(func.count())
                .select_from(ModerationDecisionReceipt)
                .where(
                    ModerationDecisionReceipt.actor_id == actor_id,
                    ModerationDecisionReceipt.idempotency_key == str(decision_key),
                )
            )
            operation_count = await session.scalar(
                select(func.count())
                .select_from(AdminOperation)
                .where(AdminOperation.id == first.id)
            )
            outbox_count = await session.scalar(
                select(func.count())
                .select_from(ModerationOutboxEvent)
                .where(ModerationOutboxEvent.id == first.id)
            )
            audit_count = await session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.entity_id == ticket_id,
                    AuditLog.action == "TICKET_DECISION_APPROVE",
                )
            )
        assert card_row is not None
        assert card_row.status is ModerationStatus.DECISION_PENDING
        assert receipt is not None and len(receipt.request_hash) == 64
        assert receipt.product_revision == 4
        assert receipt.passed_rules == ["PRODUCT_CONTENT_REVIEWED"]
        assert operation is not None and operation.status == "RUNNING"
        assert outbox is not None and outbox.status == "PENDING"
        assert decision_count == 1 and operation_count == 1
        assert outbox_count == 1 and audit_count == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_legacy_ticket_without_revision_cannot_be_claimed() -> None:
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    try:
        ticket_id, product_id, actor_id = uuid4(), uuid4(), uuid4()
        async with AsyncSession(engine) as session, session.begin():
            session.add(
                ModerationCard(
                    id=ticket_id,
                    product_id=product_id,
                    kind="CREATE",
                    status=ModerationStatus.PENDING,
                    submitted_revision=None,
                    snapshot_hash=None,
                    version=1,
                    fencing_version=0,
                )
            )

        async with AsyncSession(engine) as session:
            with pytest.raises(HTTPException) as legacy_claim:
                await ModerationService(session).claim_ticket(
                    ticket_id, actor_id, idempotency_key=uuid4()
                )
            assert legacy_claim.value.status_code == 409
            assert legacy_claim.value.detail["code"] == "REVALIDATION_REQUIRED"
            await session.rollback()

        async with AsyncSession(engine) as session:
            card = await session.get(ModerationCard, ticket_id)
            receipt_count = await session.scalar(
                select(func.count())
                .select_from(ModerationClaimReceipt)
                .where(ModerationClaimReceipt.ticket_id == ticket_id)
            )
            audit_count = await session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.entity_id == ticket_id,
                    AuditLog.action == "TICKET_CLAIM",
                )
            )
        assert card is not None
        assert card.status is ModerationStatus.PENDING
        assert card.moderator_id is None and card.fencing_version == 0
        assert receipt_count == 0 and audit_count == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_product_event_snapshot_preserves_sku_attributes_and_media() -> None:
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    try:
        event_id, product_id, sku_id = uuid4(), uuid4(), uuid4()
        event = {
            "event_id": str(event_id),
            "event_type": "PRODUCT_CREATED",
            "product_id": str(product_id),
            "aggregate_version": 7,
            "payload": {
                "snapshot_hash": "c" * 64,
                "media_refs": ["media:product-front", "media:sku-detail"],
                "json_after": {
                    "product_id": str(product_id),
                    "revision": 7,
                    "policy_version": 3,
                    "title": "Snapshot product",
                    "skus": [
                        {
                            "id": str(sku_id),
                            "name": "Snapshot SKU",
                            "attributes": {"color": "blue", "size": "M"},
                            "media_refs": ["media:sku-detail"],
                        }
                    ],
                },
            },
        }
        async with AsyncSession(engine) as session:
            result = await ModerationService(session).apply_product_event(event)
            await session.commit()

        async with AsyncSession(engine) as session:
            ticket_id = UUID(result["ticket_id"])
            card = await session.get(ModerationCard, ticket_id)
            snapshot = await session.scalar(
                select(ModerationSnapshot).where(
                    ModerationSnapshot.ticket_id == ticket_id,
                    ModerationSnapshot.revision == 7,
                )
            )
            sku = await session.scalar(
                select(ModerationSKU).where(
                    ModerationSKU.card_id == ticket_id,
                    ModerationSKU.sku_id == sku_id,
                )
            )
        assert result["status"] == "TICKET_CREATED"
        assert card is not None and card.submitted_revision == 7
        assert snapshot is not None
        assert snapshot.media_refs == ["media:product-front", "media:sku-detail"]
        assert snapshot.content["skus"][0]["attributes"] == {
            "color": "blue",
            "size": "M",
        }
        assert snapshot.content["skus"][0]["media_refs"] == ["media:sku-detail"]
        assert sku is not None and sku.name == "Snapshot SKU"
    finally:
        await engine.dispose()
