"""Decision serialization and crash-boundary checks on real PostgreSQL."""

import asyncio
import os
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from src.models.admin_operation import AdminOperation
from src.models.audit_log import AuditLog
from src.models.moderation import (
    BlockingReason,
    ModerationCard,
    ModerationSKU,
    ModerationStatus,
)
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


async def _seed_claimed_ticket(engine) -> tuple[UUID, UUID, str, int, UUID, UUID]:
    ticket_id, product_id, seller_id, sku_id = uuid4(), uuid4(), uuid4(), uuid4()
    first_actor, second_actor = uuid4(), uuid4()
    snapshot_hash = "a" * 64
    content = {
        "product_id": str(product_id),
        "revision": 4,
        "policy_version": 1,
        "attributes": {"color": "black"},
        "skus": [{"id": str(sku_id), "name": "Race SKU"}],
    }
    async with AsyncSession(engine) as session, session.begin():
        session.add_all(
            [
                StaffPrincipal(
                    id=first_actor,
                    oidc_issuer="https://issuer.test",
                    oidc_subject=f"decision-race-{first_actor}",
                    status="ACTIVE",
                ),
                StaffPrincipal(
                    id=second_actor,
                    oidc_issuer="https://issuer.test",
                    oidc_subject=f"decision-race-{second_actor}",
                    status="ACTIVE",
                ),
                ModerationCard(
                    id=ticket_id,
                    product_id=product_id,
                    seller_id=seller_id,
                    kind="CREATE",
                    status=ModerationStatus.PENDING,
                    submitted_revision=4,
                    snapshot_hash=snapshot_hash,
                    version=1,
                    fencing_version=0,
                ),
                ModerationSKU(
                    card_id=ticket_id, sku_id=sku_id, name="Race SKU"
                ),
                ModerationSnapshot(
                    ticket_id=ticket_id,
                    revision=4,
                    policy_version=1,
                    snapshot_hash=snapshot_hash,
                    content_hash=content_digest(content),
                    content=content,
                    media_refs=[],
                ),
            ]
        )
    async with AsyncSession(engine, expire_on_commit=False) as session:
        claimed = await ModerationService(session).claim_ticket(
            ticket_id, first_actor, idempotency_key=uuid4()
        )
        token, version = claimed.claim_token, claimed.version
        await session.commit()
    return ticket_id, first_actor, token, version, second_actor, seller_id


def _decision_arguments(
    action: str, claim_token: str, expected_version: int, idempotency_key: UUID
) -> dict[str, object]:
    arguments: dict[str, object] = {
        "idempotency_key": idempotency_key,
        "expected_version": expected_version,
        "action": action,
        "claim_token": claim_token,
        "product_revision": 4,
        "snapshot_hash": "a" * 64,
        "policy_version": 1,
    }
    if action == "APPROVE":
        arguments["passed_rules"] = ["PRODUCT_CONTENT_REVIEWED"]
    else:
        arguments.update(
            reason_codes=["POLICY_VIOLATION"],
            field_reports=[
                {
                    "field_path": "title",
                    "reason_code": "POLICY_VIOLATION",
                    "comment": "The submitted title violates policy.",
                }
            ],
            comment="The product cannot be published.",
        )
    return arguments


@pytest.mark.parametrize(
    ("action", "audit_action"),
    [
        ("APPROVE", "TICKET_DECISION_APPROVE"),
        ("HARD_BLOCK", "TICKET_DECISION_HARD_BLOCK"),
    ],
)
@pytest.mark.asyncio
async def test_postgres_only_one_competing_moderator_decision_commits(
    action: str, audit_action: str
) -> None:
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    try:
        ticket_id, first_actor, valid_token, version, second_actor, _ = (
            await _seed_claimed_ticket(engine)
        )
        if action == "HARD_BLOCK":
            async with AsyncSession(engine) as session, session.begin():
                session.add(
                    BlockingReason(
                        code="POLICY_VIOLATION",
                        title="Policy violation",
                        severity="HARD_BLOCK",
                        hard_block=True,
                        is_active=True,
                    )
                )

        barrier = asyncio.Barrier(2)

        async def attempt(actor_id: UUID, token: str, requested_action: str):
            async with AsyncSession(engine) as session:
                await barrier.wait()
                try:
                    receipt = await ModerationService(session).decide_ticket(
                        ticket_id,
                        actor_id,
                        **_decision_arguments(
                            requested_action, token, version, uuid4()
                        ),
                    )
                    receipt_id = receipt.id
                    await session.commit()
                    return ("ok", receipt_id)
                except HTTPException as exc:
                    await session.rollback()
                    return ("http", exc.status_code, exc.detail["code"])

        results = await asyncio.gather(
            attempt(first_actor, valid_token, action),
            attempt(
                second_actor,
                "b" * 64,
                "APPROVE" if action == "HARD_BLOCK" else action,
            ),
        )
        assert sorted(result[0] for result in results) == ["http", "ok"]
        conflict = next(result for result in results if result[0] == "http")
        assert conflict[1] in {409, 412}

        async with AsyncSession(engine) as session:
            card = await session.get(ModerationCard, ticket_id)
            decision_count = await session.scalar(
                select(func.count())
                .select_from(ModerationDecisionReceipt)
                .where(ModerationDecisionReceipt.ticket_id == ticket_id)
            )
            outbox_count = await session.scalar(
                select(func.count())
                .select_from(ModerationOutboxEvent)
                .where(ModerationOutboxEvent.id.in_(
                    select(ModerationDecisionReceipt.id).where(
                        ModerationDecisionReceipt.ticket_id == ticket_id
                    )
                ))
            )
            audit_count = await session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.entity_id == ticket_id, AuditLog.action == audit_action)
            )
            operation_count = await session.scalar(
                select(func.count())
                .select_from(AdminOperation)
                .where(
                    AdminOperation.entity_id == ticket_id,
                    AdminOperation.action == "MODERATION_DECISION",
                )
            )
        assert card is not None and card.status is ModerationStatus.DECISION_PENDING
        assert decision_count == outbox_count == audit_count == operation_count == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_two_tabs_same_moderator_only_commit_one_decision() -> None:
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    try:
        ticket_id, actor_id, claim_token, version, _, _ = await _seed_claimed_ticket(
            engine
        )
        barrier = asyncio.Barrier(2)

        async def decide_from_tab():
            async with AsyncSession(engine) as session:
                await barrier.wait()
                try:
                    receipt = await ModerationService(session).decide_ticket(
                        ticket_id,
                        actor_id,
                        **_decision_arguments(
                            "APPROVE", claim_token, version, uuid4()
                        ),
                    )
                    decision_id = receipt.id
                    await session.commit()
                    return ("ok", decision_id)
                except HTTPException as exc:
                    await session.rollback()
                    return ("http", exc.status_code, exc.detail["code"])

        results = await asyncio.gather(decide_from_tab(), decide_from_tab())
        assert sorted(result[0] for result in results) == ["http", "ok"]
        conflict = next(result for result in results if result[0] == "http")
        assert conflict[1] in {409, 412}

        async with AsyncSession(engine) as session:
            card = await session.get(ModerationCard, ticket_id)
            decision_count = await session.scalar(
                select(func.count())
                .select_from(ModerationDecisionReceipt)
                .where(ModerationDecisionReceipt.ticket_id == ticket_id)
            )
            outbox_count = await session.scalar(
                select(func.count())
                .select_from(ModerationOutboxEvent)
                .where(
                    ModerationOutboxEvent.id.in_(
                        select(ModerationDecisionReceipt.id).where(
                            ModerationDecisionReceipt.ticket_id == ticket_id
                        )
                    )
                )
            )
            audit_count = await session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.entity_id == ticket_id,
                    AuditLog.action == "TICKET_DECISION_APPROVE",
                )
            )
            operation_count = await session.scalar(
                select(func.count())
                .select_from(AdminOperation)
                .where(
                    AdminOperation.entity_id == ticket_id,
                    AdminOperation.action == "MODERATION_DECISION",
                )
            )
        assert card is not None and card.status is ModerationStatus.DECISION_PENDING
        assert decision_count == outbox_count == audit_count == operation_count == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_decision_rollback_before_commit_and_retry_after_commit() -> None:
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    try:
        ticket_id, actor_id, token, version, _, _ = await _seed_claimed_ticket(engine)
        key = uuid4()
        args = _decision_arguments("APPROVE", token, version, key)

        async with AsyncSession(engine) as session:
            await ModerationService(session).decide_ticket(ticket_id, actor_id, **args)
            await session.rollback()

        async with AsyncSession(engine) as session:
            card = await session.get(ModerationCard, ticket_id)
            decision_count = await session.scalar(
                select(func.count())
                .select_from(ModerationDecisionReceipt)
                .where(ModerationDecisionReceipt.ticket_id == ticket_id)
            )
            outbox_count = await session.scalar(
                select(func.count())
                .select_from(ModerationOutboxEvent)
                .where(
                    ModerationOutboxEvent.id.in_(
                        select(ModerationDecisionReceipt.id).where(
                            ModerationDecisionReceipt.ticket_id == ticket_id
                        )
                    )
                )
            )
            audit_count = await session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.entity_id == ticket_id,
                    AuditLog.action == "TICKET_DECISION_APPROVE",
                )
            )
            operation_count = await session.scalar(
                select(func.count())
                .select_from(AdminOperation)
                .where(
                    AdminOperation.entity_id == ticket_id,
                    AdminOperation.action == "MODERATION_DECISION",
                )
            )
        assert card is not None and card.status is ModerationStatus.IN_REVIEW
        assert decision_count == outbox_count == audit_count == operation_count == 0

        async with AsyncSession(engine, expire_on_commit=False) as session:
            committed = await ModerationService(session).decide_ticket(
                ticket_id, actor_id, **args
            )
            decision_id = committed.id
            await session.commit()

        # Model a lost response after the database commit: the client repeats
        # the same command and receives the already persisted decision.
        async with AsyncSession(engine) as session:
            replayed = await ModerationService(session).decide_ticket(
                ticket_id, actor_id, **args
            )
            assert replayed.id == decision_id

        async with AsyncSession(engine) as session:
            decision_count = await session.scalar(
                select(func.count())
                .select_from(ModerationDecisionReceipt)
                .where(ModerationDecisionReceipt.ticket_id == ticket_id)
            )
            operation_count = await session.scalar(
                select(func.count())
                .select_from(AdminOperation)
                .where(AdminOperation.id == decision_id)
            )
            outbox_count = await session.scalar(
                select(func.count())
                .select_from(ModerationOutboxEvent)
                .where(ModerationOutboxEvent.id == decision_id)
            )
            audit_count = await session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.entity_id == ticket_id,
                    AuditLog.action == "TICKET_DECISION_APPROVE",
                )
            )
        assert decision_count == operation_count == outbox_count == audit_count == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_decision_requires_and_persists_review_evidence() -> None:
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    try:
        ticket_id, actor_id, token, version, _, _ = await _seed_claimed_ticket(engine)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            service = ModerationService(session)
            invalid_requests = [
                (
                    "CHANGES_REQUESTED",
                    {
                        "reason_codes": ["POLICY_VIOLATION"],
                        "field_reports": [],
                    },
                    "FIELD_REPORTS_REQUIRED",
                ),
                (
                    "REJECT",
                    {
                        "reason_codes": ["POLICY_VIOLATION"],
                        "comment": None,
                        "field_reports": [
                            {
                                "field_path": "title",
                                "reason_code": "POLICY_VIOLATION",
                                "comment": "The title violates policy.",
                            }
                        ],
                    },
                    "DECISION_COMMENT_REQUIRED",
                ),
                (
                    "REJECT",
                    {
                        "reason_codes": ["POLICY_VIOLATION"],
                        "comment": "The product violates policy.",
                        "field_reports": [],
                    },
                    "FIELD_REPORTS_REQUIRED",
                ),
                ("APPROVE", {"passed_rules": []}, "PASSED_RULES_REQUIRED"),
            ]
            for action, extras, expected_code in invalid_requests:
                with pytest.raises(HTTPException) as rejected:
                    await service.decide_ticket(
                        ticket_id,
                        actor_id,
                        **{
                            **_decision_arguments(action, token, version, uuid4()),
                            **extras,
                        },
                    )
                assert rejected.value.status_code == 422
                assert rejected.value.detail["code"] == expected_code

            valid = await service.decide_ticket(
                ticket_id,
                actor_id,
                **_decision_arguments("APPROVE", token, version, uuid4()),
            )
            decision_id = valid.id
            await session.commit()

        async with AsyncSession(engine) as session:
            receipt = await session.get(ModerationDecisionReceipt, decision_id)
            decision_count = await session.scalar(
                select(func.count())
                .select_from(ModerationDecisionReceipt)
                .where(ModerationDecisionReceipt.ticket_id == ticket_id)
            )
        assert receipt is not None
        assert receipt.passed_rules == ["PRODUCT_CONTENT_REVIEWED"]
        assert len(receipt.request_hash) == 64
        assert decision_count == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_rejection_persists_field_report_and_policy_version() -> None:
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    try:
        ticket_id, actor_id, token, version, _, _ = await _seed_claimed_ticket(engine)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            receipt = await ModerationService(session).decide_ticket(
                ticket_id,
                actor_id,
                **_decision_arguments("REJECT", token, version, uuid4()),
            )
            await session.commit()
            persisted = await session.get(ModerationDecisionReceipt, receipt.id)
        assert persisted is not None
        assert persisted.policy_version == 1
        assert persisted.field_reports == [{
            "field_path": "title",
            "reason_code": "POLICY_VIOLATION",
            "comment": "The submitted title violates policy.",
        }]
    finally:
        await engine.dispose()
