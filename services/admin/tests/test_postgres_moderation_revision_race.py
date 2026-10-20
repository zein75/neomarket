"""Serialize a moderator decision against a newer seller revision event."""

import asyncio
import hashlib
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from src.models.admin_operation import AdminOperation
from src.models.audit_log import AuditLog
from src.models.moderation import ModerationCard, ModerationSKU, ModerationStatus
from src.models.moderation_decision_receipt import ModerationDecisionReceipt
from src.models.moderation_outbox_event import ModerationOutboxEvent
from src.models.moderation_snapshot import ModerationSnapshot
from src.models.processed_product_event import ProcessedProductEvent
from src.models.staff_principal import StaffPrincipal
from src.clients.b2b_client import B2BClient
from src.api.routers.moderation import get_ticket
from src.schemas.admin_responses import TicketDetailResponse
from src.repositories.moderation_repo import ModerationRepository
from src.schemas.moderation import PublicationDecisionEnvelope
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


@pytest.mark.asyncio
async def test_postgres_decision_rejects_unpinned_revision_and_snapshot_hash() -> None:
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    try:
        ticket_id, product_id, actor_id = uuid4(), uuid4(), uuid4()
        sku_id, snapshot_hash = uuid4(), "a" * 64
        content = {
            "product_id": str(product_id),
            "revision": 4,
            "policy_version": 1,
            "skus": [{"id": str(sku_id), "name": "Pinned SKU"}],
        }
        async with AsyncSession(engine) as session, session.begin():
            session.add_all(
                [
                    ModerationCard(
                        id=ticket_id,
                        product_id=product_id,
                        kind="CREATE",
                        status=ModerationStatus.PENDING,
                        submitted_revision=4,
                        snapshot_hash=snapshot_hash,
                        version=1,
                        fencing_version=0,
                    ),
                    ModerationSKU(
                        card_id=ticket_id, sku_id=sku_id, name="Pinned SKU"
                    ),
                    ModerationSnapshot(
                        ticket_id=ticket_id,
                        revision=4,
                        policy_version=1,
                        snapshot_hash=snapshot_hash,
                        content_hash=content_digest(content),
                        content=content,
                        media_refs=[{"id": "media-1", "state": "READY"}],
                    ),
                ]
            )

        async with AsyncSession(engine, expire_on_commit=False) as session:
            claimed = await ModerationService(session).claim_ticket(
                ticket_id, actor_id, idempotency_key=uuid4()
            )
            claim_token, expected_version = claimed.claim_token, claimed.version
            await session.commit()

        async with AsyncSession(engine, expire_on_commit=False) as session:
            service = ModerationService(session)
            mismatch_cases = [
                (5, snapshot_hash, "SNAPSHOT_STALE"),
                (4, "b" * 64, "SNAPSHOT_STALE"),
            ]
            for product_revision, supplied_hash, expected_code in mismatch_cases:
                with pytest.raises(HTTPException) as stale_decision:
                    await service.decide_ticket(
                        ticket_id,
                        actor_id,
                        idempotency_key=uuid4(),
                        expected_version=expected_version,
                        action="APPROVE",
                        claim_token=claim_token,
                        product_revision=product_revision,
                        snapshot_hash=supplied_hash,
                        passed_rules=["PRODUCT_CONTENT_REVIEWED"],
                        policy_version=1,
                    )
                assert stale_decision.value.status_code == 409
                assert stale_decision.value.detail["code"] == expected_code
            await session.commit()

        async with AsyncSession(engine) as session:
            card = await session.get(ModerationCard, ticket_id)
            snapshot = await session.scalar(
                select(ModerationSnapshot).where(
                    ModerationSnapshot.ticket_id == ticket_id,
                    ModerationSnapshot.revision == 4,
                )
            )
            decision_count = await session.scalar(
                select(func.count())
                .select_from(ModerationDecisionReceipt)
                .where(ModerationDecisionReceipt.ticket_id == ticket_id)
            )
            outbox_count = await session.scalar(
                select(func.count())
                .select_from(ModerationOutboxEvent)
                .where(
                    ModerationOutboxEvent.payload["product_id"].as_string()
                    == str(product_id)
                )
            )
        assert card is not None
        assert card.submitted_revision == 4 and card.snapshot_hash == snapshot_hash
        assert card.status is ModerationStatus.IN_REVIEW
        assert snapshot is not None and snapshot.content["revision"] == 4
        assert snapshot.snapshot_hash == snapshot_hash
        assert decision_count == 0 and outbox_count == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_ticket_detail_compares_submitted_with_published_revision(monkeypatch) -> None:
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    try:
        ticket_id, product_id, seller_id, actor_id = (
            uuid4(),
            uuid4(),
            uuid4(),
            uuid4(),
        )
        sku_id = uuid4()
        submitted = {
            "product_id": str(product_id),
            "category_id": str(uuid4()),
            "revision": 7,
            "policy_version": 2,
            "title": "Revised title",
            "description": "Revised description",
            "attributes": {"color": "blue"},
            "skus": [
                {
                    "id": str(sku_id),
                    "name": "Revised SKU",
                    "price_minor": 1299,
                    "currency": "RUB",
                    "attributes": {"size": "M"},
                }
            ],
        }
        source_hash, content_hash = "a" * 64, content_digest(submitted)
        async with AsyncSession(engine) as session, session.begin():
            session.add_all(
                [
                    StaffPrincipal(
                        id=actor_id,
                        oidc_issuer="https://issuer.test",
                        oidc_subject=f"ticket-detail-{actor_id}",
                        status="ACTIVE",
                    ),
                    ModerationCard(
                        id=ticket_id,
                        product_id=product_id,
                        seller_id=seller_id,
                        kind="UPDATE",
                        status=ModerationStatus.PENDING,
                        submitted_revision=7,
                        snapshot_hash=source_hash,
                        version=1,
                        fencing_version=0,
                    ),
                    ModerationSKU(
                        card_id=ticket_id, sku_id=sku_id, name="Revised SKU"
                    ),
                    ModerationSnapshot(
                        ticket_id=ticket_id,
                        revision=7,
                        policy_version=2,
                        snapshot_hash=source_hash,
                        content_hash=content_hash,
                        content=submitted,
                        media_refs=[],
                    ),
                ]
            )

        async def fake_b2b_read(_client, path: str) -> dict[str, object]:
            if path.endswith("/publication"):
                return {
                    "product_id": str(product_id),
                    "current_revision": 7,
                    "published_revision": 6,
                    "visible": True,
                    "visibility_reasons": [],
                }
            if path.endswith("/revisions/6"):
                return {
                    "product_id": str(product_id),
                    "seller_id": str(seller_id),
                    "revision": 6,
                    "snapshot_hash": "b" * 64,
                    "media_refs": [],
                    "content": {
                        "product_id": str(product_id),
                        "category_id": str(uuid4()),
                        "revision": 6,
                        "policy_version": 1,
                        "title": "Published title",
                        "description": "Published description",
                        "attributes": {"color": "red"},
                        "skus": [
                            {
                                "id": str(sku_id),
                                "name": "Published SKU",
                                "price_minor": 999,
                                "currency": "RUB",
                                "attributes": {"size": "S"},
                            }
                        ],
                    },
                }
            raise AssertionError(f"unexpected B2B path: {path}")

        monkeypatch.setattr(B2BClient, "get_internal_json", fake_b2b_read)
        async with AsyncSession(engine) as session:
            response = await get_ticket(
                ticket_id, SimpleNamespace(id=actor_id), session
            )
        contract = TicketDetailResponse.model_validate(response)
        assert contract.snapshot.revision == 7
        assert contract.published_revision == 6
        assert contract.field_diff is not None
        diff_by_path = {item.path: item for item in contract.field_diff}
        assert diff_by_path["title"].before == "Published title"
        assert diff_by_path["title"].after == "Revised title"
        assert diff_by_path["attributes.color"].before == "red"
        assert diff_by_path["attributes.color"].after == "blue"
        sku_diff = diff_by_path["skus"]
        assert sku_diff.before[0]["price_minor"] == 999
        assert sku_diff.after[0]["price_minor"] == 1299
        checklist = {item.code: item for item in contract.checklist}
        assert checklist["TITLE_RULES"].passed is True
        assert checklist["CATEGORY_RULES"].passed is True
        assert checklist["SKU_RULES"].passed is True
        assert checklist["SKU_PRICE_RULES"].passed is True
        # The fixture deliberately has no media refs; the detail response must
        # expose the blocking media check instead of silently presenting a
        # complete review.
        assert checklist["MEDIA_RULES"].passed is False
        assert "media" in (checklist["MEDIA_RULES"].message or "").lower()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_new_revision_serializes_after_decision_and_stales_it(monkeypatch) -> None:
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    try:
        ticket_id, product_id, seller_id, actor_id = uuid4(), uuid4(), uuid4(), uuid4()
        sku_id, idempotency_key, edit_event_id = uuid4(), uuid4(), uuid4()
        revision, initial_version, fencing_version = 4, 2, 1
        claim_token = "test-claim-token-which-is-never-stored-plaintext"
        snapshot_hash = "a" * 64
        content = {
            "product_id": str(product_id),
            "revision": revision,
            "policy_version": 1,
            "skus": [{"id": str(sku_id), "name": "Original SKU"}],
        }
        card = ModerationCard(
            id=ticket_id,
            product_id=product_id,
            seller_id=seller_id,
            kind="CREATE",
            status=ModerationStatus.IN_REVIEW,
            moderator_id=actor_id,
            submitted_revision=revision,
            snapshot_hash=snapshot_hash,
            version=initial_version,
            fencing_version=fencing_version,
            lease_token_hash=hashlib.sha256(claim_token.encode()).hexdigest(),
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        )
        async with AsyncSession(engine) as session, session.begin():
            session.add(
                StaffPrincipal(
                    id=actor_id,
                    oidc_issuer="https://issuer.test",
                    oidc_subject=f"revision-race-{actor_id}",
                    status="ACTIVE",
                )
            )
            await session.flush()
            session.add_all(
                [
                    card,
                    ModerationSKU(card_id=ticket_id, sku_id=sku_id, name="Original SKU"),
                    ModerationSnapshot(
                        ticket_id=ticket_id,
                        revision=revision,
                        policy_version=1,
                        snapshot_hash=snapshot_hash,
                        content_hash=content_digest(content),
                        content=content,
                        media_refs=[],
                    ),
                ]
            )

        decision_has_row_lock = asyncio.Event()
        allow_decision_commit = asyncio.Event()
        revision_query_started = asyncio.Event()
        original_ticket_lock = ModerationRepository.get_with_skus_for_update
        original_product_lock = ModerationRepository.get_by_product_id_for_update

        async def pause_decision_after_lock(repository, candidate_ticket_id):
            result = await original_ticket_lock(repository, candidate_ticket_id)
            if candidate_ticket_id == ticket_id:
                decision_has_row_lock.set()
                await allow_decision_commit.wait()
            return result

        async def note_revision_lock(repository, candidate_product_id):
            if candidate_product_id == product_id:
                revision_query_started.set()
            return await original_product_lock(repository, candidate_product_id)

        monkeypatch.setattr(
            ModerationRepository, "get_with_skus_for_update", pause_decision_after_lock
        )
        monkeypatch.setattr(
            ModerationRepository, "get_by_product_id_for_update", note_revision_lock
        )

        async def decide() -> UUID:
            async with AsyncSession(engine) as session:
                await session.execute(
                    text("SET application_name = 'admin-race-decision'")
                )
                receipt = await ModerationService(session).decide_ticket(
                    ticket_id,
                    actor_id,
                    idempotency_key=idempotency_key,
                    expected_version=initial_version,
                    action="APPROVE",
                    claim_token=claim_token,
                    product_revision=revision,
                    snapshot_hash=snapshot_hash,
                    passed_rules=["PRODUCT_CONTENT_REVIEWED"],
                    policy_version=1,
                )
                receipt_id = receipt.id
                await session.commit()
                return receipt_id

        async def seller_edit() -> dict[str, str]:
            async with AsyncSession(engine) as session:
                await session.execute(
                    text("SET application_name = 'admin-race-revision'")
                )
                result = await ModerationService(session).apply_product_event(
                    {
                        "event_id": str(edit_event_id),
                        "event_type": "PRODUCT_EDITED",
                        "product_id": str(product_id),
                        "seller_id": str(seller_id),
                        "aggregate_version": revision + 1,
                        "occurred_at": datetime.now(timezone.utc),
                        "payload": {
                            "snapshot_hash": "c" * 64,
                            "media_refs": [],
                            "json_after": {
                                "product_id": str(product_id),
                                "revision": revision + 1,
                                "policy_version": 1,
                                "title": "Edited while moderation was in progress",
                                "skus": [
                                    {"id": str(sku_id), "name": "Updated SKU"}
                                ],
                            },
                        },
                    }
                )
                await session.commit()
                return result

        decision_task = asyncio.create_task(decide())
        await asyncio.wait_for(decision_has_row_lock.wait(), timeout=5)
        edit_task = asyncio.create_task(seller_edit())
        await asyncio.wait_for(revision_query_started.wait(), timeout=5)
        # The revision handler has started its SELECT FOR UPDATE while the
        # decision transaction owns the ticket row; release the winner next.
        await asyncio.sleep(0.05)
        allow_decision_commit.set()
        decision_id = await asyncio.wait_for(decision_task, timeout=10)
        edit_result = await asyncio.wait_for(edit_task, timeout=10)
        assert edit_result["status"] == "TICKET_CREATED"

        async with AsyncSession(engine) as session:
            original = await session.get(ModerationCard, ticket_id)
            new_card = await session.scalar(
                select(ModerationCard).where(
                    ModerationCard.product_id == product_id,
                    ModerationCard.submitted_revision == revision + 1,
                )
            )
            decision = await session.get(ModerationDecisionReceipt, decision_id)
            outbox = await session.get(ModerationOutboxEvent, decision_id)
            operation = await session.get(AdminOperation, decision_id)
            edit_receipt = await session.get(ProcessedProductEvent, edit_event_id)
        assert original is not None and original.status is ModerationStatus.STALE
        assert original.version == initial_version + 2
        assert original.moderator_id is None and original.lease_token_hash is None
        assert new_card is not None and new_card.status is ModerationStatus.PENDING
        assert new_card.submitted_revision == revision + 1
        assert decision is not None and decision.result_status == "DECISION_PENDING"
        assert outbox is not None and outbox.status == "PENDING"
        assert operation is not None and operation.status == "RUNNING"
        assert edit_receipt is not None

        # The only valid completion is B2B's durable revision-conflict result;
        # a command-accepted response alone must not make this product public.
        result_event = PublicationDecisionEnvelope.model_validate(
            {
                "schema_version": 1,
                "event_id": uuid4(),
                "event_type": "product.publication.rejected.v1",
                "producer": "b2b",
                "aggregate_type": "product",
                "aggregate_id": product_id,
                "aggregate_version": revision + 1,
                "occurred_at": datetime.now(timezone.utc),
                "correlation_id": idempotency_key,
                "payload": {
                    "decision_id": decision_id,
                    "product_id": product_id,
                    "submitted_revision": revision,
                    "action": "APPROVE",
                    "published_revision": None,
                    "visible": False,
                    "reason_code": "REVISION_CONFLICT",
                },
            }
        )
        async with AsyncSession(engine) as session:
            result = await ModerationService(session).apply_publication_decision_event(
                result_event
            )
            await session.commit()
        assert result == {"status": "REJECTED"}

        async with AsyncSession(engine) as session:
            original = await session.get(ModerationCard, ticket_id)
            outbox = await session.get(ModerationOutboxEvent, decision_id)
            operation = await session.get(AdminOperation, decision_id)
            result_receipt = await session.get(ProcessedProductEvent, result_event.event_id)
            result_audit = await session.scalar(
                select(AuditLog).where(
                    AuditLog.entity_id == ticket_id,
                    AuditLog.action == "MODERATION_DECISION_REJECTED",
                )
            )
        assert original is not None and original.status is ModerationStatus.STALE
        assert original.version == initial_version + 3
        assert outbox is not None and outbox.status == "BLOCKED"
        assert operation is not None and operation.status == "FAILED"
        assert result_receipt is not None and result_audit is not None
    finally:
        await engine.dispose()
