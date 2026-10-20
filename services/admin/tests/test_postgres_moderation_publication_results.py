"""Durable B2B publication result handling against Admin PostgreSQL."""

import os
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.requests import Request

from src.api.routers.iam import get_operation
from src.models.admin_operation import AdminOperation
from src.models.audit_log import AuditLog
from src.models.moderation import ModerationCard, ModerationStatus
from src.models.moderation_decision_receipt import ModerationDecisionReceipt
from src.models.moderation_outbox_event import ModerationOutboxEvent
from src.models.processed_product_event import ProcessedProductEvent
from src.models.staff_principal import StaffPrincipal
from src.schemas.moderation import PublicationDecisionEnvelope
from src.services.moderation_service import ModerationService

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


def _operation_request(operation_id) -> Request:
    path = f"/admin/v1/operations/{operation_id}"
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [],
        "server": ("admin.test", 80),
        "client": ("127.0.0.1", 12345),
        "root_path": "",
        "path_params": {"operation_id": str(operation_id)},
    }
    request = Request(scope)
    request.state.request_id = str(uuid4())
    return request


async def _seed_pending_decision(
    engine, *, action: str = "APPROVE"
) -> dict[str, object]:
    ticket_id, product_id, decision_id, actor_id, idempotency_key = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    revision = 4
    request_hash = "f" * 64
    card = ModerationCard(
        id=ticket_id,
        product_id=product_id,
        seller_id=uuid4(),
        kind="CREATE",
        status=ModerationStatus.DECISION_PENDING,
        moderator_id=actor_id,
        submitted_revision=revision,
        snapshot_hash="a" * 64,
        version=3,
        fencing_version=2,
        lease_token_hash="b" * 64,
    )
    decision = ModerationDecisionReceipt(
        id=decision_id,
        ticket_id=ticket_id,
        actor_id=actor_id,
        idempotency_key=str(idempotency_key),
        request_hash=request_hash,
        action=action,
        product_revision=revision,
        snapshot_hash=card.snapshot_hash,
        policy_version=1,
        reason_codes=[],
        passed_rules=["PRODUCT_CONTENT_REVIEWED"] if action == "APPROVE" else [],
        field_reports=[],
        comment=None,
        result_status="DECISION_PENDING",
    )
    outbox = ModerationOutboxEvent(
        id=decision_id,
        idempotency_key=str(idempotency_key),
        event_type="MODERATION_DECISION",
        payload={
            "decision_id": str(decision_id),
            "product_id": str(product_id),
            "submitted_revision": revision,
            "snapshot_hash": card.snapshot_hash,
            "policy_version": 1,
            "action": action,
            "correlation_id": str(idempotency_key),
        },
        status="WAITING_ACK",
        attempts=1,
    )
    operation = AdminOperation(
        id=decision_id,
        action="MODERATION_DECISION",
        entity_type="moderation_ticket",
        entity_id=ticket_id,
        payload={
            "decision_id": str(decision_id),
            "product_id": str(product_id),
            "submitted_revision": revision,
            "action": action,
            "policy_version": 1,
        },
        status="RUNNING",
        version=1,
        idempotency_key=f"moderation:{idempotency_key}",
        request_hash=request_hash,
        requested_by=actor_id,
        reason_code="MODERATION_DECISION",
    )
    async with AsyncSession(engine) as session, session.begin():
        session.add(
            StaffPrincipal(
                id=actor_id,
                oidc_issuer="https://issuer.test",
                oidc_subject=f"publication-{actor_id}",
                status="ACTIVE",
            )
        )
        await session.flush()
        session.add_all([card, decision, outbox, operation])
    return {
        "ticket_id": ticket_id,
        "product_id": product_id,
        "decision_id": decision_id,
        "actor_id": actor_id,
        "idempotency_key": idempotency_key,
        "revision": revision,
    }


def _result_event(
    seeded: dict[str, object],
    *,
    event_type: str,
    event_id=None,
    aggregate_version: int | None = None,
    reason_code: str | None = None,
) -> PublicationDecisionEnvelope:
    revision = int(seeded["revision"])
    applied = event_type == "product.publication.applied.v1"
    return PublicationDecisionEnvelope.model_validate(
        {
            "schema_version": 1,
            "event_id": event_id or uuid4(),
            "event_type": event_type,
            "producer": "b2b",
            "aggregate_type": "product",
            "aggregate_id": seeded["product_id"],
            "aggregate_version": aggregate_version
            or (revision if applied else revision + 1),
            "occurred_at": datetime.now(timezone.utc),
            "correlation_id": seeded["idempotency_key"],
            "payload": {
                "decision_id": seeded["decision_id"],
                "product_id": seeded["product_id"],
                "submitted_revision": revision,
                "action": "APPROVE",
                "published_revision": revision if applied else None,
                "visible": True if applied else False,
                "reason_code": reason_code,
            },
        }
    )


@pytest.mark.asyncio
async def test_postgres_applied_publication_result_resolves_and_replays() -> None:
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    try:
        seeded = await _seed_pending_decision(engine)
        event = _result_event(seeded, event_type="product.publication.applied.v1")
        actor = SimpleNamespace(
            id=seeded["actor_id"],
            permissions={"operations.read"},
            permission_scopes={"operations.read": {"*"}},
        )

        async with AsyncSession(engine, expire_on_commit=False) as session:
            pending_status = await get_operation(
                operation_id=seeded["decision_id"],
                request=_operation_request(seeded["decision_id"]),
                response=Response(),
                actor=actor,
                db=session,
            )
            assert pending_status.status == "RUNNING"
            result = await ModerationService(session).apply_publication_decision_event(
                event
            )
            await session.commit()
        assert result == {"status": "APPLIED"}

        async with AsyncSession(engine, expire_on_commit=False) as session:
            card = await session.get(ModerationCard, seeded["ticket_id"])
            outbox = await session.get(ModerationOutboxEvent, seeded["decision_id"])
            operation = await session.get(AdminOperation, seeded["decision_id"])
            receipt_count = await session.scalar(
                select(func.count())
                .select_from(ProcessedProductEvent)
                .where(ProcessedProductEvent.event_id == event.event_id)
            )
            audit_count = await session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.entity_id == seeded["ticket_id"],
                    AuditLog.action == "MODERATION_DECISION_APPLIED",
                )
            )
            resolved_status = await get_operation(
                operation_id=seeded["decision_id"],
                request=_operation_request(seeded["decision_id"]),
                response=Response(),
                actor=actor,
                db=session,
            )
        assert card is not None and card.status is ModerationStatus.MODERATED
        assert outbox is not None and outbox.status == "SENT"
        assert operation is not None and operation.status == "APPLIED"
        assert resolved_status.status == "APPLIED"
        assert receipt_count == 1 and audit_count == 1

        async with AsyncSession(engine) as session:
            replay = await ModerationService(session).apply_publication_decision_event(
                event
            )
            await session.commit()
        assert replay == {"status": "ALREADY_APPLIED"}

        conflicting_replay = event.model_copy(
            update={"payload": event.payload.model_copy(update={"visible": False})}
        )
        async with AsyncSession(engine) as session:
            with pytest.raises(HTTPException) as conflict:
                await ModerationService(session).apply_publication_decision_event(
                    conflicting_replay
                )
            await session.rollback()
        assert conflict.value.status_code == 409
        assert conflict.value.detail["code"] == "EVENT_ID_CONFLICT"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_rejected_publication_result_marks_ticket_stale() -> None:
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    try:
        seeded = await _seed_pending_decision(engine)
        event = _result_event(
            seeded,
            event_type="product.publication.rejected.v1",
            reason_code="REVISION_CONFLICT",
        )
        async with AsyncSession(engine) as session:
            result = await ModerationService(session).apply_publication_decision_event(
                event
            )
            await session.commit()
        assert result == {"status": "REJECTED"}

        async with AsyncSession(engine) as session:
            card = await session.get(ModerationCard, seeded["ticket_id"])
            outbox = await session.get(ModerationOutboxEvent, seeded["decision_id"])
            operation = await session.get(AdminOperation, seeded["decision_id"])
            receipt = await session.get(ProcessedProductEvent, event.event_id)
        assert card is not None and card.status is ModerationStatus.STALE
        assert card.moderator_id is None and card.lease_token_hash is None
        assert outbox is not None and outbox.status == "BLOCKED"
        assert outbox.last_error == "REVISION_CONFLICT"
        assert operation is not None and operation.status == "FAILED"
        assert receipt is not None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_publication_result_must_match_decision_correlation() -> None:
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    try:
        seeded = await _seed_pending_decision(engine)
        event = _result_event(seeded, event_type="product.publication.applied.v1")
        event = event.model_copy(update={"correlation_id": uuid4()})
        async with AsyncSession(engine) as session:
            with pytest.raises(HTTPException) as mismatch:
                await ModerationService(session).apply_publication_decision_event(event)
            await session.rollback()
        assert mismatch.value.status_code == 409
        assert mismatch.value.detail["code"] == "DECISION_RECEIPT_MISMATCH"
        async with AsyncSession(engine) as session:
            card = await session.get(ModerationCard, seeded["ticket_id"])
            receipt = await session.get(ProcessedProductEvent, event.event_id)
        assert card is not None and card.status is ModerationStatus.DECISION_PENDING
        assert receipt is None
    finally:
        await engine.dispose()
