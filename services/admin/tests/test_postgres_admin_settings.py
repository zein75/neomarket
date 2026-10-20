"""Admin settings inventories must be permission-gated and fail closed."""

import os
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from fastapi import HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.requests import Request

from src.api.deps import _staff_access, require_permission
from src.api.routers import iam, integrations, sessions
from src.api.routers.iam import approve_operation
from src.api.routers.policies import propose_policy_publish
from src.api.routers.integrations import propose_runtime_settings
from src.api.routers.appeals import propose_appeal_decision
from src.api.routers.complaints import complaint_action, ingest_complaint
from src.api.routers.sessions import create_web_session
from src.models.audit_log import AuditLog
from src.models.admin_operation import AdminOperation
from src.models.admin_policy import AdminPolicy
from src.models.admin_web_session import AdminWebSession
from src.models.appeal import Appeal
from src.models.complaint import Complaint
from src.models.moderation import ModerationCard, ModerationStatus
from src.models.moderation_decision_receipt import ModerationDecisionReceipt
from src.models.moderation_snapshot import ModerationSnapshot
from src.models.staff_principal import StaffPrincipal, StaffRoleGrant
from src.schemas.admin import PublishInput, ReasonAction, RuntimeSettingsProposalInput
from src.services.runtime_settings import effective_values
from src.services.moderation_service import ModerationService
from src.services.product_snapshots import content_digest
from src.workers import outbox
from src.schemas.appeals import AppealAction
from src.schemas.casework import ComplaintAction, ComplaintIntake

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
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
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
    request = Request(scope)
    request.state.request_id = str(uuid4())
    return request


async def _actor(session: AsyncSession, role: str) -> SimpleNamespace:
    principal = StaffPrincipal(
        id=uuid4(),
        oidc_issuer="https://issuer.test",
        oidc_subject=f"settings-{role}-{uuid4()}",
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


def _queue_values(claim_ttl: int = 1200, complaint_sla: int = 43200) -> dict[str, int]:
    return {
        "moderation_claim_ttl_seconds": claim_ttl,
        "complaint_case_sla_seconds": complaint_sla,
    }


def _workflow_values(idle_ttl: int = 2400) -> dict[str, int | float]:
    return {
        "admin_session_idle_ttl_seconds": idle_ttl,
        "admin_session_absolute_ttl_seconds": 86400,
        "admin_step_up_max_age_seconds": 600,
        "moderation_outbox_poll_interval_seconds": 1.5,
    }


async def _approve_settings_operation(
    session: AsyncSession,
    operation_id,
    reviewer: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(iam, "require_recent_step_up", lambda _actor: None)
    await approve_operation(
        operation_id=operation_id,
        data=ReasonAction(reason_code="RUNTIME_SETTINGS_CHANGE"),
        request=_request(f"/admin/v1/operations/{operation_id}/approve"),
        idempotency_key=uuid4(),
        if_match='"1"',
        current=reviewer,
        db=session,
    )


async def _publish_settings_policy(
    session: AsyncSession,
    creator: SimpleNamespace,
    reviewer: SimpleNamespace,
    publisher: SimpleNamespace,
    section: str,
    values: dict[str, int | float],
    expected_version: int,
    monkeypatch: pytest.MonkeyPatch,
) -> AdminPolicy:
    proposal = await propose_runtime_settings(
        section,
        RuntimeSettingsProposalInput(
            expected_version=expected_version,
            values=values,
            reason_code="RUNTIME_SETTINGS_CHANGE",
        ),
        _request(f"/admin/v1/settings/{section}/versions"),
        uuid4(),
        creator,
        session,
    )
    assert proposal.status == "WAITING_APPROVAL"
    with pytest.raises(HTTPException) as maker_checker:
        await _approve_settings_operation(
            session, proposal.operation_id, creator, monkeypatch
        )
    assert maker_checker.value.status_code == 403
    assert maker_checker.value.detail["code"] == "MAKER_CHECKER_VIOLATION"
    await _approve_settings_operation(session, proposal.operation_id, reviewer, monkeypatch)
    policy = await session.get(AdminPolicy, proposal.resource_id)
    assert policy is not None and policy.status == "APPROVED"
    assert await session.scalar(
        select(func.count())
        .select_from(AuditLog)
        .where(
            AuditLog.entity_id == policy.id,
            AuditLog.action.in_(
                ("POLICY_CREATE_PROPOSED", "POLICY_CREATE_APPROVED")
            ),
        )
    ) == 2

    publication = await propose_policy_publish(
        policy_id=policy.id,
        data=PublishInput(
            impact_hash=policy.content_hash,
            reason_code="RUNTIME_SETTINGS_CHANGE",
        ),
        request=_request(f"/admin/v1/policies/{policy.id}/publish"),
        idempotency_key=uuid4(),
        if_match=f'"{policy.version}"',
        actor=reviewer,
        db=session,
    )
    await _approve_settings_operation(session, publication.operation_id, publisher, monkeypatch)
    await session.refresh(policy)
    assert policy.status == "PUBLISHED"
    return policy


@pytest.mark.asyncio
async def test_postgres_settings_inventory_is_private_secret_free_and_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            reader = await _actor(session, "security_admin")
            ordinary_staff = await _actor(session, "support_viewer")

            for name, value in (
                ("oidc_issuer", "https://idp.example.test/issuer"),
                ("oidc_jwks_url", "https://idp.example.test/.well-known/jwks.json"),
                ("oidc_audience", "neomarket-admin"),
                ("oidc_required_amr", "mfa"),
                ("oidc_required_acr", ""),
                ("oidc_step_up_required_amr", "step_up"),
                ("oidc_step_up_required_acr", ""),
            ):
                monkeypatch.setattr(integrations.settings, name, value)

            integrations_request = _request("/admin/v1/settings/integrations")
            permission = require_permission("settings.read")
            with pytest.raises(HTTPException) as denied_integrations:
                await permission(integrations_request, ordinary_staff, session)
            assert denied_integrations.value.status_code == 403

            authorized_reader = await permission(integrations_request, reader, session)
            integrations_response = await integrations.get_integration_status(
                current=authorized_reader,
                db=session,
            )
            assert integrations_response.as_of.tzinfo is not None
            by_key = {item.key: item for item in integrations_response.items}
            assert by_key["identity_provider"].status == "CONFIGURED_UNVERIFIED"
            assert "reachability is not checked" in by_key["identity_provider"].detail
            assert by_key["mfa_step_up"].status == "CONFIGURED_UNVERIFIED"
            assert by_key["case_notice_delivery"].status == "NOT_CONFIGURED"
            assert "complaint_close" in by_key["case_notice_delivery"].blocked_actions
            assert by_key["evidence_av_scan"].status == "NOT_CONFIGURED"
            assert "evidence_review" in by_key["evidence_av_scan"].blocked_actions
            assert (
                "secret"
                not in str(integrations_response.model_dump(mode="json")).lower()
            )

            settings_request = _request("/admin/v1/settings")
            with pytest.raises(HTTPException) as denied_runtime:
                await permission(settings_request, ordinary_staff, session)
            assert denied_runtime.value.status_code == 403

            authorized_reader = await permission(settings_request, reader, session)
            runtime_response = await integrations.get_runtime_settings(
                current=authorized_reader,
                db=session,
            )
            runtime_by_key = {item.key: item for item in runtime_response.items}
            assert runtime_response.as_of.tzinfo is not None
            assert runtime_by_key["queue_policy"].status == "CONFIGURED_UNVERSIONED"
            assert runtime_by_key["queue_policy"].source == "environment"
            assert (
                runtime_by_key["workflow_settings"].status == "CONFIGURED_UNVERSIONED"
            )
            assert runtime_by_key["workflow_settings"].source == "environment"
            assert runtime_by_key["notification_settings"].status == "NOT_CONFIGURED"
            assert runtime_by_key["notification_settings"].writable is False
            assert (
                runtime_by_key["retention_status"].status == "BLOCKED_PENDING_DECISION"
            )
            assert runtime_by_key["retention_status"].writable is False
            assert runtime_by_key["deployment_settings"].writable is False
            assert runtime_by_key["moderation_sla"].writable is False
            assert runtime_by_key["safety_hold_policy"].writable is False
            assert "secret" not in str(runtime_response.model_dump(mode="json")).lower()

            audited_reads = await session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.actor_id == reader.id,
                    AuditLog.action.in_(
                        ("ADMIN_INTEGRATION_STATUS_READ", "ADMIN_RUNTIME_SETTINGS_READ")
                    ),
                )
            )
            assert audited_reads == 2
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_notice_dependent_case_actions_fail_closed_without_writes() -> (
    None
):
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            actor = SimpleNamespace(
                id=uuid4(), permissions={"complaint.decide", "appeal.decide"}
            )
            complaint_id = uuid4()
            complaint_request = _request(f"/admin/v1/complaints/{complaint_id}/actions")

            for action in ("REQUEST_INFO", "WARN", "CLOSE"):
                with pytest.raises(HTTPException) as blocked:
                    await complaint_action(
                        complaint_id=complaint_id,
                        data=ComplaintAction(
                            action=action, reason_code="NOTICE_REQUIRED"
                        ),
                        request=complaint_request,
                        idempotency_key=uuid4(),
                        if_match='"v1"',
                        current=actor,
                        db=session,
                    )
                assert blocked.value.status_code == 503
                assert blocked.value.detail["code"] == "NOTICE_DELIVERY_NOT_CONFIGURED"

            appeal_id = uuid4()
            ticket_id = uuid4()
            original_actor_id = uuid4()
            original_receipt = ModerationDecisionReceipt(
                id=uuid4(),
                ticket_id=ticket_id,
                actor_id=original_actor_id,
                idempotency_key=f"notice-appeal-{uuid4()}",
                request_hash="a" * 64,
                action="APPROVE",
                product_revision=1,
                snapshot_hash="b" * 64,
                policy_version=1,
                reason_codes=["APPROVED"],
                passed_rules=[],
                field_reports=[],
                result_status="APPLIED",
            )
            session.add_all(
                [
                    ModerationCard(
                        id=ticket_id,
                        product_id=uuid4(),
                        kind="CREATE",
                        status=ModerationStatus.MODERATED,
                        submitted_revision=1,
                        snapshot_hash="b" * 64,
                        version=1,
                        fencing_version=0,
                    ),
                    original_receipt,
                ]
            )
            await session.flush()
            session.add(
                Appeal(
                    id=appeal_id,
                    source_event_id=uuid4(),
                    original_decision_id=original_receipt.id,
                    claimant_ref="c" * 64,
                    evidence_refs=[],
                )
            )
            await session.flush()
            with pytest.raises(HTTPException) as appeal_blocked:
                await propose_appeal_decision(
                    appeal_id=appeal_id,
                    data=AppealAction(
                        outcome="UPHELD",
                        reason_code="NOTICE_REQUIRED",
                        comment="Synthetic notice-dependent appeal result",
                    ),
                    request=_request(f"/admin/v1/appeals/{appeal_id}/decisions"),
                    idempotency_key=uuid4(),
                    if_match='"1"',
                    current=actor,
                    db=session,
                )
            assert appeal_blocked.value.status_code == 503
            assert (
                appeal_blocked.value.detail["code"] == "NOTICE_DELIVERY_NOT_CONFIGURED"
            )

            operations = await session.scalar(
                select(func.count())
                .select_from(AdminOperation)
                .where(AdminOperation.requested_by == actor.id)
            )
            assert operations == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_runtime_settings_publish_versions_and_reject_stale_or_gated_changes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            creator = await _actor(session, "security_admin")
            reviewer = await _actor(session, "security_admin")
            publisher = await _actor(session, "security_admin")
            reader = await _actor(session, "security_admin")

            queue_policy = await _publish_settings_policy(
                session,
                creator,
                reviewer,
                publisher,
                "queue_policy",
                _queue_values(),
                0,
                monkeypatch,
            )
            queue_values, queue_version = await effective_values(session, "queue_policy")
            assert queue_values == _queue_values()
            assert queue_version == queue_policy.version == 1

            workflow_policy = await _publish_settings_policy(
                session,
                creator,
                reviewer,
                publisher,
                "workflow_settings",
                _workflow_values(),
                0,
                monkeypatch,
            )
            workflow_values, workflow_version = await effective_values(
                session, "workflow_settings"
            )
            assert workflow_values == _workflow_values()
            assert workflow_version == workflow_policy.version == 1

            settings_request = _request("/admin/v1/settings")
            authorized_reader = await require_permission("settings.read")(
                settings_request, reader, session
            )
            response = await integrations.get_runtime_settings(
                current=authorized_reader, db=session
            )
            by_key = {item.key: item for item in response.items}
            assert by_key["queue_policy"].source == "database"
            assert by_key["queue_policy"].version == queue_policy.version
            assert by_key["queue_policy"].values == _queue_values()
            assert by_key["workflow_settings"].source == "database"
            assert by_key["workflow_settings"].version == workflow_policy.version
            assert by_key["workflow_settings"].values == _workflow_values()

            complaint_intake = ComplaintIntake(
                event_id=uuid4(),
                source="B2C",
                reporter_ref="a" * 64,
                entity_type="PRODUCT",
                entity_id=uuid4(),
                category="SAFETY",
            )
            await ingest_complaint(complaint_intake, session)
            complaint = await session.scalar(
                select(Complaint).where(
                    Complaint.source_event_id == complaint_intake.event_id
                )
            )
            assert complaint is not None and complaint.deadline_at is not None
            assert (
                43199
                <= (complaint.deadline_at - complaint.created_at).total_seconds()
                <= 43201
            )

            card_id, product_id = uuid4(), uuid4()
            snapshot_content = {"product_id": str(product_id), "revision": 7}
            snapshot_hash = "b" * 64
            card = ModerationCard(
                id=card_id,
                product_id=product_id,
                status=ModerationStatus.PENDING,
                submitted_revision=7,
                snapshot_hash=snapshot_hash,
                version=1,
                fencing_version=0,
            )
            session.add(card)
            session.add(
                ModerationSnapshot(
                    ticket_id=card_id,
                    revision=7,
                    policy_version=1,
                    snapshot_hash=snapshot_hash,
                    content_hash=content_digest(snapshot_content),
                    content=snapshot_content,
                    media_refs=[],
                )
            )
            await session.flush()
            claimed = await ModerationService(session).claim_ticket(
                card_id, reviewer.id, idempotency_key=uuid4()
            )
            assert claimed.lease_expires_at is not None
            assert (
                1199
                <= (claimed.lease_expires_at - claimed.updated_at).total_seconds()
                <= 1201
            )
            await session.commit()

            monkeypatch.setattr(
                sessions.settings, "admin_public_origin", "https://admin.test"
            )
            oidc_actor = SimpleNamespace(
                id=creator.id,
                source="oidc",
                mfa_verified=True,
                session_expires_at=datetime.now(timezone.utc) + timedelta(days=2),
                oidc_jti_hash=f"settings-jti-{uuid4()}",
            )
            session_request = _request("/admin/v1/auth/session")
            session_request.scope["headers"] = [
                (b"origin", b"https://admin.test"),
                (b"user-agent", b"Admin runtime settings integration"),
            ]
            await create_web_session(
                request=session_request,
                response=Response(),
                current=oidc_actor,
                db=session,
            )
            web_session = await session.scalar(
                select(AdminWebSession).where(
                    AdminWebSession.principal_id == creator.id
                )
            )
            assert web_session is not None
            assert (
                2399
                <= (web_session.idle_expires_at - web_session.created_at).total_seconds()
                <= 2401
            )

            poll_intervals: list[float] = []
            monkeypatch.setattr(
                outbox, "AsyncSessionLocal", lambda: AsyncSession(engine)
            )
            monkeypatch.setattr(outbox, "_HEARTBEAT", tmp_path / "admin-worker.json")
            monkeypatch.setattr(outbox, "record_worker_metric", lambda *_args: None)

            class IdleModerationService:
                def __init__(self, _db):
                    pass

                async def retry_pending_decisions(self):
                    return 0

            monkeypatch.setattr(outbox, "ModerationService", IdleModerationService)
            stop = asyncio.Event()

            async def capture_worker_interval(awaitable, *, timeout):
                poll_intervals.append(timeout)
                stop.set()
                return await awaitable

            monkeypatch.setattr(outbox.asyncio, "wait_for", capture_worker_interval)
            await outbox.moderation_outbox_worker(stop)
            assert poll_intervals == [1.5]

            # Two proposals may be prepared against one base. After one is
            # published, approval of the other must preserve the active version.
            first = await propose_runtime_settings(
                "queue_policy",
                RuntimeSettingsProposalInput(
                    expected_version=1,
                    values=_queue_values(1500, 43200),
                    reason_code="RUNTIME_SETTINGS_CHANGE",
                ),
                _request("/admin/v1/settings/queue_policy/versions"),
                uuid4(),
                creator,
                session,
            )
            stale = await propose_runtime_settings(
                "queue_policy",
                RuntimeSettingsProposalInput(
                    expected_version=1,
                    values=_queue_values(1800, 43200),
                    reason_code="RUNTIME_SETTINGS_CHANGE",
                ),
                _request("/admin/v1/settings/queue_policy/versions"),
                uuid4(),
                creator,
                session,
            )
            stale_publish = await propose_runtime_settings(
                "queue_policy",
                RuntimeSettingsProposalInput(
                    expected_version=1,
                    values=_queue_values(1600, 43200),
                    reason_code="RUNTIME_SETTINGS_CHANGE",
                ),
                _request("/admin/v1/settings/queue_policy/versions"),
                uuid4(),
                creator,
                session,
            )
            await _approve_settings_operation(session, first.operation_id, reviewer, monkeypatch)
            await _approve_settings_operation(
                session, stale_publish.operation_id, reviewer, monkeypatch
            )
            stale_publish_policy = await session.get(
                AdminPolicy, stale_publish.resource_id
            )
            assert stale_publish_policy is not None
            first_policy = await session.get(AdminPolicy, first.resource_id)
            assert first_policy is not None
            publish = await propose_policy_publish(
                policy_id=first_policy.id,
                data=PublishInput(
                    impact_hash=first_policy.content_hash,
                    reason_code="RUNTIME_SETTINGS_CHANGE",
                ),
                request=_request(f"/admin/v1/policies/{first_policy.id}/publish"),
                idempotency_key=uuid4(),
                if_match=f'"{first_policy.version}"',
                actor=reviewer,
                db=session,
            )
            await _approve_settings_operation(session, publish.operation_id, publisher, monkeypatch)
            stale_publication = await propose_policy_publish(
                policy_id=stale_publish_policy.id,
                data=PublishInput(
                    impact_hash=stale_publish_policy.content_hash,
                    reason_code="RUNTIME_SETTINGS_CHANGE",
                ),
                request=_request(
                    f"/admin/v1/policies/{stale_publish_policy.id}/publish"
                ),
                idempotency_key=uuid4(),
                if_match=f'"{stale_publish_policy.version}"',
                actor=reviewer,
                db=session,
            )
            with pytest.raises(HTTPException) as stale_publication_approval:
                await _approve_settings_operation(
                    session,
                    stale_publication.operation_id,
                    publisher,
                    monkeypatch,
                )
            assert stale_publication_approval.value.status_code == 412
            assert (
                stale_publication_approval.value.detail["code"]
                == "RUNTIME_POLICY_VERSION_MISMATCH"
            )
            with pytest.raises(HTTPException) as stale_approval:
                await _approve_settings_operation(session, stale.operation_id, reviewer, monkeypatch)
            assert stale_approval.value.status_code == 412
            assert stale_approval.value.detail["code"] == "RUNTIME_POLICY_VERSION_MISMATCH"
            active_values, active_version = await effective_values(session, "queue_policy")
            assert active_values == _queue_values(1500, 43200)
            assert active_version == 2
            stale_row = await session.get(AdminOperation, stale.operation_id)
            assert stale_row is not None and stale_row.status == "WAITING_APPROVAL"

            proposals_before_validation = await session.scalar(
                select(func.count())
                .select_from(AdminOperation)
                .where(
                    AdminOperation.requested_by == creator.id,
                    AdminOperation.action == "POLICY_CREATE",
                )
            )
            for invalid_values, expected_version, error_code in (
                ({**_queue_values(), "retention_days": 30}, 2, "INVALID_RUNTIME_POLICY"),
                (_queue_values(), 1, "RUNTIME_POLICY_VERSION_MISMATCH"),
            ):
                with pytest.raises(HTTPException) as invalid_proposal:
                    await propose_runtime_settings(
                        "queue_policy",
                        RuntimeSettingsProposalInput(
                            expected_version=expected_version,
                            values=invalid_values,
                            reason_code="RUNTIME_SETTINGS_CHANGE",
                        ),
                        _request("/admin/v1/settings/queue_policy/versions"),
                        uuid4(),
                        creator,
                        session,
                    )
                assert invalid_proposal.value.status_code in {412, 422}
                assert invalid_proposal.value.detail["code"] == error_code
            assert await session.scalar(
                select(func.count())
                .select_from(AdminOperation)
                .where(
                    AdminOperation.requested_by == creator.id,
                    AdminOperation.action == "POLICY_CREATE",
                )
            ) == proposals_before_validation

            before_gated_proposals = await session.scalar(
                select(func.count())
                .select_from(AdminOperation)
                .where(
                    AdminOperation.requested_by == creator.id,
                    AdminOperation.action == "POLICY_CREATE",
                )
            )
            app = FastAPI()
            app.include_router(integrations.router)
            target_route = next(
                route
                for route in app.routes
                if getattr(route, "path", None)
                == "/admin/v1/settings/{section}/versions"
            )
            async def override_db():
                yield session

            for dependency in target_route.dependant.dependencies:
                if dependency.name == "actor":
                    app.dependency_overrides[dependency.call] = lambda: creator
                elif dependency.name == "db":
                    app.dependency_overrides[dependency.call] = override_db

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="https://admin.test"
            ) as client:
                for gated_section in (
                    "moderation_sla",
                    "safety_hold_policy",
                    "retention_status",
                    "deployment_settings",
                ):
                    blocked = await client.post(
                        f"/admin/v1/settings/{gated_section}/versions",
                        json={
                            "expected_version": 0,
                            "values": {},
                            "reason_code": "RUNTIME_SETTINGS_CHANGE",
                        },
                    )
                    assert blocked.status_code == 422

            assert await session.scalar(
                select(func.count())
                .select_from(AdminOperation)
                .where(
                    AdminOperation.requested_by == creator.id,
                    AdminOperation.action == "POLICY_CREATE",
                )
            ) == before_gated_proposals
    finally:
        await engine.dispose()
