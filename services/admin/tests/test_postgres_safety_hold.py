"""Safety-hold maker-checker behavior against PostgreSQL persistence."""

import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.requests import Request

from src.api.deps import _staff_access
from src.api.routers import iam, products
from src.api.routers.iam import approve_operation
from src.core.config import settings
from src.models.admin_operation import AdminOperation
from src.models.audit_log import AuditLog
from src.models.moderation_outbox_event import ModerationOutboxEvent
from src.models.staff_principal import StaffPrincipal, StaffRoleGrant
from src.schemas.admin import ReasonAction
from src.schemas.products import HoldInput

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


def _request(path: str) -> Request:
    request = Request(
        {
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
        }
    )
    request.state.request_id = str(uuid4())
    return request


async def _actor(session: AsyncSession, role: str) -> SimpleNamespace:
    principal = StaffPrincipal(
        id=uuid4(),
        oidc_issuer="https://issuer.test",
        oidc_subject=f"hold-{role}-{uuid4()}",
        status="ACTIVE",
    )
    session.add(principal)
    session.add(
        StaffRoleGrant(principal_id=principal.id, role=role, scope_key="global")
    )
    await session.flush()
    roles, permissions, scopes = await _staff_access(
        principal, session, datetime.now(timezone.utc)
    )
    return SimpleNamespace(
        id=principal.id,
        roles=roles,
        permissions=permissions,
        permission_scopes=scopes,
        mfa_verified=True,
        step_up_verified=True,
    )


class FakeB2BClient:
    product_id = None
    calls = 0

    async def get_internal_json(self, path: str) -> dict[str, object]:
        type(self).calls += 1
        assert path == f"/internal/v1/products/{self.product_id}/publication"
        return {
            "product_id": str(self.product_id),
            "current_revision": 7,
            "published_revision": 6,
            "visible": True,
            "visibility_reasons": [],
        }


def _hold(*, seconds: int) -> HoldInput:
    return HoldInput(
        reason_code="SAFETY_REVIEW",
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=seconds),
        comment="Synthetic safety review",
    )


async def _propose_hold(
    session: AsyncSession,
    actor: SimpleNamespace,
    product_id,
    hold: HoldInput,
):
    return await products.request_product_safety_hold(
        product_id=product_id,
        data=hold,
        request=_request(f"/admin/v1/products/{product_id}/safety-hold"),
        if_match='"v7"',
        idempotency_key=uuid4(),
        actor=actor,
        db=session,
    )


@pytest.mark.asyncio
async def test_postgres_short_safety_hold_is_revision_bound_queued_and_audited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    product_id = uuid4()
    try:
        monkeypatch.setattr(settings, "admin_safety_hold_max_seconds", 3600)
        monkeypatch.setattr(products, "B2BClient", FakeB2BClient)
        FakeB2BClient.product_id = product_id
        FakeB2BClient.calls = 0
        async with AsyncSession(engine, expire_on_commit=False) as session:
            proposer = await _actor(session, "trust_safety")
            response = await _propose_hold(
                session, proposer, product_id, _hold(seconds=600)
            )
            assert response.status == "QUEUED"
            operation = await session.get(AdminOperation, response.operation_id)
            event = await session.scalar(
                select(ModerationOutboxEvent).where(
                    ModerationOutboxEvent.idempotency_key
                    == f"admin-command:{response.operation_id}"
                )
            )
            audit = await session.scalar(
                select(AuditLog).where(
                    AuditLog.action == "PRODUCT_SAFETY_HOLD_PROPOSED",
                    AuditLog.entity_id == product_id,
                )
            )
            assert operation is not None and operation.status == "QUEUED"
            assert operation.payload["expected_version"] == 7
            assert event is not None and event.status == "PENDING"
            command = event.payload["command"]
            assert command["expected_version"] == 7
            assert command["payload"]["expires_at"] == operation.payload[
                "command_payload"
            ]["expires_at"]
            assert audit is not None
            assert audit.details["maker_checker_required"] is False
            assert audit.details["revision"] == 7
            assert FakeB2BClient.calls == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_long_safety_hold_requires_independent_current_policy_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    product_id = uuid4()
    try:
        monkeypatch.setattr(settings, "admin_safety_hold_max_seconds", 3600)
        monkeypatch.setattr(products, "B2BClient", FakeB2BClient)
        monkeypatch.setattr(iam, "require_recent_step_up", lambda _actor: None)
        FakeB2BClient.product_id = product_id
        FakeB2BClient.calls = 0
        async with AsyncSession(engine, expire_on_commit=False) as session:
            proposer = await _actor(session, "trust_safety")
            approver = await _actor(session, "trust_safety")
            response = await _propose_hold(
                session, proposer, product_id, _hold(seconds=7200)
            )
            assert response.status == "WAITING_APPROVAL"
            assert await session.scalar(
                select(func.count())
                .select_from(ModerationOutboxEvent)
                .where(
                    ModerationOutboxEvent.idempotency_key
                    == f"admin-command:{response.operation_id}"
                )
            ) == 0

            with pytest.raises(HTTPException) as self_approval:
                await approve_operation(
                    operation_id=response.operation_id,
                    data=ReasonAction(reason_code="SAFETY_REVIEW"),
                    request=_request(
                        f"/admin/v1/operations/{response.operation_id}/approve"
                    ),
                    idempotency_key=uuid4(),
                    if_match='"1"',
                    current=proposer,
                    db=session,
                )
            assert self_approval.value.status_code == 403
            assert self_approval.value.detail["code"] == "MAKER_CHECKER_VIOLATION"

            monkeypatch.setattr(settings, "admin_safety_hold_max_seconds", 7200)
            with pytest.raises(HTTPException) as stale_policy:
                await approve_operation(
                    operation_id=response.operation_id,
                    data=ReasonAction(reason_code="SAFETY_REVIEW"),
                    request=_request(
                        f"/admin/v1/operations/{response.operation_id}/approve"
                    ),
                    idempotency_key=uuid4(),
                    if_match='"1"',
                    current=approver,
                    db=session,
                )
            assert stale_policy.value.status_code == 409
            assert stale_policy.value.detail["code"] == "SAFETY_HOLD_POLICY_CHANGED"
            assert await session.scalar(
                select(func.count())
                .select_from(ModerationOutboxEvent)
                .where(
                    ModerationOutboxEvent.idempotency_key
                    == f"admin-command:{response.operation_id}"
                )
            ) == 0

            monkeypatch.setattr(settings, "admin_safety_hold_max_seconds", 3600)
            real_datetime = datetime

            class ExpiredClock(datetime):
                @classmethod
                def now(cls, tz=None):
                    return real_datetime.now(tz) + timedelta(hours=3)

            with monkeypatch.context() as frozen:
                frozen.setattr(iam, "datetime", ExpiredClock)
                with pytest.raises(HTTPException) as expired:
                    await approve_operation(
                        operation_id=response.operation_id,
                        data=ReasonAction(reason_code="SAFETY_REVIEW"),
                        request=_request(
                            f"/admin/v1/operations/{response.operation_id}/approve"
                        ),
                        idempotency_key=uuid4(),
                        if_match='"1"',
                        current=approver,
                        db=session,
                    )
            assert expired.value.status_code == 409
            assert expired.value.detail["code"] == "SAFETY_HOLD_EXPIRED"

            approved = await approve_operation(
                operation_id=response.operation_id,
                data=ReasonAction(reason_code="SAFETY_REVIEW"),
                request=_request(
                    f"/admin/v1/operations/{response.operation_id}/approve"
                ),
                idempotency_key=uuid4(),
                if_match='"1"',
                current=approver,
                db=session,
            )
            assert approved.status == "QUEUED"
            event = await session.scalar(
                select(ModerationOutboxEvent).where(
                    ModerationOutboxEvent.idempotency_key
                    == f"admin-command:{response.operation_id}"
                )
            )
            operation = await session.get(AdminOperation, response.operation_id)
            assert event is not None and event.status == "PENDING"
            assert event.payload["command"]["approved_by_staff_id"] == str(
                approver.id
            )
            assert operation is not None and operation.status == "QUEUED"
            assert operation.approved_by == approver.id
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_missing_safety_hold_policy_creates_no_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    product_id = uuid4()
    try:
        monkeypatch.setattr(settings, "admin_safety_hold_max_seconds", None)
        monkeypatch.setattr(products, "B2BClient", FakeB2BClient)
        FakeB2BClient.product_id = product_id
        FakeB2BClient.calls = 0
        async with AsyncSession(engine, expire_on_commit=False) as session:
            proposer = await _actor(session, "trust_safety")
            outbox_before = await session.scalar(
                select(func.count()).select_from(ModerationOutboxEvent)
            )
            with pytest.raises(HTTPException) as blocked:
                await _propose_hold(
                    session, proposer, product_id, _hold(seconds=600)
                )
            assert blocked.value.status_code == 503
            assert blocked.value.detail["code"] == "SAFETY_HOLD_POLICY_NOT_CONFIGURED"
            assert await session.scalar(
                select(func.count())
                .select_from(AdminOperation)
                .where(AdminOperation.requested_by == proposer.id)
            ) == 0
            assert await session.scalar(
                select(func.count()).select_from(ModerationOutboxEvent)
            ) == outbox_before
            assert FakeB2BClient.calls == 0
    finally:
        await engine.dispose()
