"""Complaint casework contracts backed by the real Admin PostgreSQL schema."""

import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, HTTPException, Response
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.requests import Request

from src.api import deps
from src.api.deps import _staff_access, require_permission
from src.api.routers import appeals as appeals_router
from src.api.routers import complaints as complaints_router
from src.api.routers.appeals import (
    get_appeal,
    get_appeal_evidence,
    ingest_appeal,
    list_appeals,
    propose_appeal_decision,
)
from src.api.routers.complaints import (
    complaint_action,
    get_complaint,
    get_complaint_evidence,
    ingest_complaint,
    list_complaints,
)
from src.api.routers.moderation import dashboard
from src.api.routers.iam import approve_operation, get_operation
from src.models.admin_operation import AdminOperation
from src.models.audit_log import AuditLog
from src.models.appeal import Appeal
from src.models.complaint import Complaint
from src.models.moderation import ModerationCard, ModerationStatus
from src.models.moderation_decision_receipt import ModerationDecisionReceipt
from src.models.moderation_outbox_event import ModerationOutboxEvent
from src.models.staff_principal import StaffPrincipal, StaffRoleGrant
from src.schemas.appeals import AppealAction, AppealIntake
from src.schemas.admin import ReasonAction
from src.schemas.casework import ComplaintAction, ComplaintIntake
from src.services.operational_metrics import render_operational_metrics
from src.services.audit_context import bind_actor_context

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


def _request(
    path: str, *, method: str = "GET", path_params: dict[str, str] | None = None
) -> Request:
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [],
        "server": ("admin.test", 80),
        "client": ("127.0.0.1", 12345),
        "root_path": "",
        "path_params": path_params or {},
    }
    request = Request(scope)
    request.state.request_id = str(uuid4())
    return request


def _intake(
    *, event_id: UUID | None = None, entity_id: UUID | None = None
) -> ComplaintIntake:
    return ComplaintIntake(
        event_id=event_id or uuid4(),
        source="B2C",
        reporter_ref="a" * 64,
        entity_type="PRODUCT",
        entity_id=entity_id or uuid4(),
        category="ITEM_NOT_AS_DESCRIBED",
        priority=4,
        evidence_refs=["b" * 64],
    )


async def _principal(session: AsyncSession, role: str) -> SimpleNamespace:
    principal = StaffPrincipal(
        id=uuid4(),
        oidc_issuer="https://issuer.test",
        oidc_subject=f"casework-{role}-{uuid4()}",
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
        step_up_expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )


@pytest.mark.asyncio
async def test_postgres_complaint_intake_is_idempotent_and_persists_sla() -> None:
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            data = _intake()
            result = await ingest_complaint(data, session)
            complaint_id = result["complaint_id"]
            assert result["status"] == "NEW"

            complaint = await session.get(Complaint, complaint_id)
            assert complaint is not None
            assert complaint.deadline_at is not None
            assert complaint.deadline_at > complaint.created_at
            assert complaint.reporter_ref == data.reporter_ref.lower()
            assert complaint.evidence_refs == ["b" * 64]

            retry = await ingest_complaint(data, session)
            assert retry == result

            changed = data.model_copy(update={"category": "UNSAFE_PRODUCT"})
            with pytest.raises(HTTPException) as conflict:
                await ingest_complaint(changed, session)
            assert conflict.value.status_code == 409
            assert conflict.value.detail["code"] == "EVENT_ID_REUSED"

            invalid_evidence = data.model_copy(
                update={"event_id": uuid4(), "evidence_refs": ["not-a-sha256"]}
            )
            with pytest.raises(HTTPException) as invalid:
                await ingest_complaint(invalid_evidence, session)
            assert invalid.value.status_code == 422
            assert invalid.value.detail["code"] == "INVALID_EVIDENCE_REF"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_case_assignment_scopes_evidence_and_timeline() -> None:
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            support = await _principal(session, "support_viewer")
            trust = await _principal(session, "trust_safety")
            data = _intake()
            intake_result = await ingest_complaint(data, session)
            complaint_id = intake_result["complaint_id"]

            unassigned = await list_complaints(
                cursor=None, limit=100, current=trust, db=session
            )
            assert any(item["id"] == str(complaint_id) for item in unassigned["items"])
            complaint_path = f"/admin/v1/complaints/{complaint_id}"
            detail_response = Response()
            trust_detail = await get_complaint(
                complaint_id=complaint_id,
                request=_request(
                    complaint_path,
                    path_params={"complaint_id": str(complaint_id)},
                ),
                response=detail_response,
                current=trust,
                db=session,
            )
            assert trust_detail.id == complaint_id
            assert detail_response.headers["etag"] == '"1"'
            support_before_assignment = await list_complaints(
                cursor=None, limit=100, current=support, db=session
            )
            assert all(
                item["id"] != str(complaint_id)
                for item in support_before_assignment["items"]
            )
            with pytest.raises(HTTPException) as hidden:
                await get_complaint(
                    complaint_id=complaint_id,
                    request=_request(
                        complaint_path,
                        path_params={"complaint_id": str(complaint_id)},
                    ),
                    response=Response(),
                    current=support,
                    db=session,
                )
            assert hidden.value.status_code == 404

            assignment = await complaint_action(
                complaint_id=complaint_id,
                data=ComplaintAction(
                    action="ASSIGN",
                    reason_code="ROUTE_TO_SUPPORT",
                    assignee_staff_id=support.id,
                ),
                request=_request(
                    f"/admin/v1/complaints/{complaint_id}/actions",
                    method="POST",
                    path_params={"complaint_id": str(complaint_id)},
                ),
                idempotency_key=uuid4(),
                if_match='"v1"',
                current=trust,
                db=session,
            )
            assert assignment.status == "APPLIED"
            decision_permission = require_permission("complaint.decide")
            with pytest.raises(HTTPException) as cannot_decide:
                await decision_permission(
                    _request(
                        f"{complaint_path}/actions",
                        method="POST",
                        path_params={"complaint_id": str(complaint_id)},
                    ),
                    support,
                    session,
                )
            assert cannot_decide.value.status_code == 403

            support_after_assignment = await list_complaints(
                cursor=None, limit=100, current=support, db=session
            )
            assert any(
                item["id"] == str(complaint_id)
                for item in support_after_assignment["items"]
            )

            detail = await get_complaint(
                complaint_id=complaint_id,
                request=_request(
                    complaint_path, path_params={"complaint_id": str(complaint_id)}
                ),
                response=Response(),
                current=support,
                db=session,
            )
            detail_payload = detail.model_dump(mode="json")
            assert "evidence_refs" not in detail_payload
            assert "reporter_ref" not in detail_payload
            assert [entry.action for entry in detail.timeline] == [
                "COMPLAINT_CREATED",
                "COMPLAINT_ASSIGN",
            ]
            assert all("comment" not in entry.model_dump() for entry in detail.timeline)

            evidence_path = f"{complaint_path}/evidence"
            evidence_request = _request(
                evidence_path, path_params={"complaint_id": str(complaint_id)}
            )
            evidence_permission = require_permission("complaint.evidence.read")
            with pytest.raises(HTTPException) as denied:
                await evidence_permission(evidence_request, support, session)
            assert denied.value.status_code == 403

            authorized = await evidence_permission(evidence_request, trust, session)
            evidence = await get_complaint_evidence(
                complaint_id=complaint_id,
                request=evidence_request,
                current=authorized,
                db=session,
            )
            assert evidence.evidence_refs == ["b" * 64]
            assert evidence.scan_status == "NOT_CONFIGURED"
            audit_count = await session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.entity_type == "complaint",
                    AuditLog.entity_id == complaint_id,
                    AuditLog.action == "COMPLAINT_EVIDENCE_READ",
                )
            )
            assert audit_count == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_support_viewer_cannot_fetch_private_evidence_routes() -> None:
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            support = await _principal(session, "support_viewer")
            trust = await _principal(session, "trust_safety")
            ticket_id, decision_id = uuid4(), uuid4()
            complaint_id, appeal_id = uuid4(), uuid4()
            session.add_all(
                [
                    ModerationCard(
                        id=ticket_id,
                        product_id=uuid4(),
                        seller_id=uuid4(),
                        status=ModerationStatus.MODERATED,
                    ),
                    Complaint(
                        id=complaint_id,
                        source_event_id=uuid4(),
                        source="B2C",
                        reporter_ref="a" * 64,
                        entity_type="PRODUCT",
                        entity_id=uuid4(),
                        category="PRIVATE_EVIDENCE_TEST",
                        status="NEW",
                        priority=3,
                        evidence_refs=["b" * 64],
                    ),
                    ModerationDecisionReceipt(
                        id=decision_id,
                        ticket_id=ticket_id,
                        actor_id=uuid4(),
                        idempotency_key=f"support-evidence-{uuid4()}",
                        request_hash="c" * 64,
                        action="APPROVE",
                        product_revision=1,
                        snapshot_hash="d" * 64,
                        policy_version=1,
                        reason_codes=["POLICY_COMPLIANT"],
                        passed_rules=["REQUIRED_FIELDS"],
                        result_status="APPLIED",
                    ),
                ]
            )
            await session.flush()
            session.add(
                Appeal(
                    id=appeal_id,
                    source_event_id=uuid4(),
                    original_decision_id=decision_id,
                    claimant_ref="e" * 64,
                    evidence_refs=["f" * 64],
                    status="SUBMITTED",
                    version=1,
                )
            )
            await session.commit()

            active_actor = support

            async def current_actor() -> SimpleNamespace:
                bind_actor_context(active_actor.id, active_actor.roles)
                return active_actor

            async def database_session() -> AsyncSession:
                return session

            app = FastAPI()
            app.include_router(complaints_router.router)
            app.include_router(appeals_router.router)
            app.dependency_overrides[deps.get_current_moderator] = current_actor
            app.dependency_overrides[deps.get_db] = database_session
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="https://admin.test"
            ) as client:
                complaint_denied = await client.get(
                    f"/admin/v1/complaints/{complaint_id}/evidence"
                )
                appeal_denied = await client.get(
                    f"/admin/v1/appeals/{appeal_id}/evidence"
                )
                assert complaint_denied.status_code == 403
                assert appeal_denied.status_code == 403
                assert complaint_denied.json()["detail"]["code"] == "PERMISSION_DENIED"
                assert appeal_denied.json()["detail"]["code"] == "PERMISSION_DENIED"

                active_actor = trust
                complaint_allowed = await client.get(
                    f"/admin/v1/complaints/{complaint_id}/evidence"
                )
                appeal_allowed = await client.get(
                    f"/admin/v1/appeals/{appeal_id}/evidence"
                )
                assert complaint_allowed.status_code == 200
                assert complaint_allowed.json()["evidence_refs"] == ["b" * 64]
                assert appeal_allowed.status_code == 200
                assert appeal_allowed.json()["evidence_refs"] == ["f" * 64]

            denial_events = (
                await session.scalars(
                    select(AuditLog).where(
                        AuditLog.actor_id == support.id,
                        AuditLog.action == "ADMIN_ACCESS_DENIED",
                        AuditLog.details["required_permission"].as_string().in_(
                            ["complaint.evidence.read", "appeal.evidence.read"]
                        ),
                    )
                )
            ).all()
            assert len(denial_events) == 2
            assert {event.details["required_permission"] for event in denial_events} == {
                "complaint.evidence.read",
                "appeal.evidence.read",
            }
            allowed_evidence_reads = await session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.actor_id == trust.id,
                    AuditLog.action.in_(["COMPLAINT_EVIDENCE_READ", "APPEAL_EVIDENCE_READ"]),
                )
            )
            assert allowed_evidence_reads == 2
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_complaint_queue_keyset_order_and_index() -> None:
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            support = await _principal(session, "support_viewer")
            timestamp = datetime.now(timezone.utc).replace(microsecond=0)
            ids = [UUID(int=uuid4().int) for _ in range(3)]
            rows = [
                Complaint(
                    id=ids[0],
                    source_event_id=uuid4(),
                    source="B2C",
                    reporter_ref="c" * 64,
                    entity_type="PRODUCT",
                    entity_id=uuid4(),
                    category="QUEUE_TEST",
                    status="NEW",
                    priority=5,
                    assigned_to=support.id,
                    created_at=timestamp,
                ),
                Complaint(
                    id=ids[1],
                    source_event_id=uuid4(),
                    source="B2C",
                    reporter_ref="d" * 64,
                    entity_type="PRODUCT",
                    entity_id=uuid4(),
                    category="QUEUE_TEST",
                    status="NEW",
                    priority=5,
                    assigned_to=support.id,
                    created_at=timestamp,
                ),
                Complaint(
                    id=ids[2],
                    source_event_id=uuid4(),
                    source="B2C",
                    reporter_ref="e" * 64,
                    entity_type="PRODUCT",
                    entity_id=uuid4(),
                    category="QUEUE_TEST",
                    status="NEW",
                    priority=4,
                    assigned_to=support.id,
                    created_at=timestamp - timedelta(seconds=1),
                ),
            ]
            session.add_all(rows)
            await session.flush()
            expected_ids = [
                str(row.id)
                for row in sorted(
                    rows, key=lambda row: (-row.priority, row.created_at, row.id.int)
                )
            ]

            first = await list_complaints(
                cursor=None, limit=2, current=support, db=session
            )
            assert [item["id"] for item in first["items"]] == expected_ids[:2]
            assert first["page"]["has_more"] is True
            second = await list_complaints(
                cursor=first["page"]["next_cursor"],
                limit=2,
                current=support,
                db=session,
            )
            assert [item["id"] for item in second["items"]] == expected_ids[2:]
            assert second["page"]["has_more"] is False

            index_exists = await session.scalar(
                text(
                    "SELECT to_regclass('public.ix_admin_complaints_queue_order') IS NOT NULL"
                )
            )
            assert index_exists is True
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_complaint_dashboard_and_metrics_report_live_sla_counts() -> (
    None
):
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    try:
        now = datetime.now(timezone.utc)
        complaint = Complaint(
            id=uuid4(),
            source_event_id=uuid4(),
            source="B2C",
            reporter_ref="f" * 64,
            entity_type="PRODUCT",
            entity_id=uuid4(),
            category="METRICS_TEST",
            status="NEW",
            priority=2,
            evidence_refs=[],
            created_at=now - timedelta(seconds=120),
            deadline_at=now - timedelta(seconds=30),
        )
        in_review = Complaint(
            id=uuid4(),
            source_event_id=uuid4(),
            source="B2C",
            reporter_ref="1" * 64,
            entity_type="PRODUCT",
            entity_id=uuid4(),
            category="METRICS_TEST",
            status="IN_REVIEW",
            priority=3,
            evidence_refs=[],
            created_at=now - timedelta(seconds=60),
        )
        async with AsyncSession(engine, expire_on_commit=False) as session:
            before = await dashboard(SimpleNamespace(), session)
            before_new = await session.scalar(
                select(func.count())
                .select_from(Complaint)
                .where(Complaint.status == "NEW")
            )
            session.add_all((complaint, in_review))
            await session.flush()

            after = await dashboard(SimpleNamespace(), session)
            assert after["as_of"] >= before["as_of"]
            assert after["complaints_pending"] == before["complaints_pending"] + 1
            assert after["complaints_in_review"] == before["complaints_in_review"] + 1
            assert after["complaints_overdue"] == before["complaints_overdue"] + 1
            assert after["oldest_complaint_pending_seconds"] >= 120
            assert after["provenance"]["complaints"].startswith("admin_complaints.")

            metrics = await render_operational_metrics(session)
            expected_new = int(before_new or 0) + 1
            assert f'admin_complaint_cases{{status="NEW"}} {expected_new}' in metrics
            assert 'admin_complaint_cases{status="IN_REVIEW"}' in metrics
            oldest_line = next(
                line
                for line in metrics.splitlines()
                if line.startswith("admin_complaint_oldest_pending_seconds ")
            )
            overdue_line = next(
                line
                for line in metrics.splitlines()
                if line.startswith("admin_complaint_overdue_cases ")
            )
            assert int(oldest_line.rsplit(" ", 1)[1]) >= 120
            assert int(overdue_line.rsplit(" ", 1)[1]) >= 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_appeal_detail_and_evidence_keep_private_data_separate() -> None:
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            support = await _principal(session, "support_viewer")
            trust = await _principal(session, "trust_safety")
            senior = await _principal(session, "senior_moderator")
            ticket_id = uuid4()
            decision_id = uuid4()
            actor_id = uuid4()
            session.add(
                ModerationCard(
                    id=ticket_id,
                    product_id=uuid4(),
                    seller_id=uuid4(),
                    status=ModerationStatus.MODERATED,
                )
            )
            session.add(
                ModerationDecisionReceipt(
                    id=decision_id,
                    ticket_id=ticket_id,
                    actor_id=actor_id,
                    idempotency_key=f"appeal-decision-{uuid4()}",
                    request_hash="a" * 64,
                    action="APPROVE",
                    product_revision=7,
                    snapshot_hash="b" * 64,
                    policy_version=3,
                    reason_codes=["POLICY_COMPLIANT"],
                    passed_rules=["REQUIRED_FIELDS"],
                    result_status="APPLIED",
                )
            )
            await session.flush()

            intake = AppealIntake(
                event_id=uuid4(),
                original_decision_id=decision_id,
                claimant_ref="c" * 64,
                evidence_refs=["d" * 64],
            )
            result = await ingest_appeal(intake, session)
            appeal_id = result["appeal_id"]
            assert result["status"] == "SUBMITTED"

            action = AppealAction(
                outcome="UPHELD",
                reason_code="REVIEWED",
                comment="Independent review fixture",
            )
            with pytest.raises(HTTPException) as self_decision:
                await propose_appeal_decision(
                    appeal_id=appeal_id,
                    data=action,
                    request=_request(
                        f"/admin/v1/appeals/{appeal_id}/decisions",
                        method="POST",
                        path_params={"appeal_id": str(appeal_id)},
                    ),
                    idempotency_key=uuid4(),
                    if_match='"1"',
                    current=SimpleNamespace(id=actor_id),
                    db=session,
                )
            assert self_decision.value.status_code == 403
            assert self_decision.value.detail["code"] == "APPEAL_REVIEWER_NOT_INDEPENDENT"

            with pytest.raises(HTTPException) as notice_blocked:
                await propose_appeal_decision(
                    appeal_id=appeal_id,
                    data=action,
                    request=_request(
                        f"/admin/v1/appeals/{appeal_id}/decisions",
                        method="POST",
                        path_params={"appeal_id": str(appeal_id)},
                    ),
                    idempotency_key=uuid4(),
                    if_match='"1"',
                    current=senior,
                    db=session,
                )
            assert notice_blocked.value.status_code == 503
            assert notice_blocked.value.detail["code"] == "NOTICE_DELIVERY_NOT_CONFIGURED"

            detail = await get_appeal(
                appeal_id=appeal_id,
                request=_request(
                    f"/admin/v1/appeals/{appeal_id}",
                    path_params={"appeal_id": str(appeal_id)},
                ),
                current=support,
                db=session,
            )
            payload = detail.model_dump(mode="json")
            assert "claimant_ref" not in payload
            assert "evidence_refs" not in payload
            assert detail.original_decision.actor_id == actor_id
            assert detail.original_decision.action == "APPROVE"
            assert detail.original_decision.product_revision == 7
            assert [item.action for item in detail.timeline] == ["APPEAL_SUBMITTED"]

            senior_queue = await list_appeals(
                cursor=None, limit=20, actor=senior, db=session
            )
            assert any(item["id"] == str(appeal_id) for item in senior_queue["items"])
            senior_detail = await get_appeal(
                appeal_id=appeal_id,
                request=_request(
                    f"/admin/v1/appeals/{appeal_id}",
                    path_params={"appeal_id": str(appeal_id)},
                ),
                current=senior,
                db=session,
            )
            assert senior_detail.original_decision.actor_id == actor_id
            assert senior_detail.original_decision.actor_id != senior.id

            evidence_request = _request(
                f"/admin/v1/appeals/{appeal_id}/evidence",
                path_params={"appeal_id": str(appeal_id)},
            )
            evidence_permission = require_permission("appeal.evidence.read")
            with pytest.raises(HTTPException) as denied:
                await evidence_permission(evidence_request, support, session)
            assert denied.value.status_code == 403
            authorized = await evidence_permission(evidence_request, trust, session)
            evidence = await get_appeal_evidence(
                appeal_id=appeal_id,
                request=evidence_request,
                current=authorized,
                db=session,
            )
            assert evidence.evidence_refs == ["d" * 64]
            assert evidence.scan_status == "NOT_CONFIGURED"
            audit_count = await session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.entity_type == "appeal",
                    AuditLog.entity_id == appeal_id,
                    AuditLog.action == "APPEAL_EVIDENCE_READ",
                )
            )
            assert audit_count == 1
            assert await session.get(Appeal, appeal_id) is not None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_complaint_safety_action_remains_partial_until_b2b_receipt() -> (
    None
):
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            proposer = await _principal(session, "trust_safety")
            approver = await _principal(session, "security_admin")
            intake_result = await ingest_complaint(_intake(), session)
            complaint_id = intake_result["complaint_id"]
            assignment = await complaint_action(
                complaint_id=complaint_id,
                data=ComplaintAction(
                    action="ASSIGN",
                    reason_code="ROUTE_FOR_SAFETY_REVIEW",
                    assignee_staff_id=proposer.id,
                ),
                request=_request(
                    f"/admin/v1/complaints/{complaint_id}/actions",
                    method="POST",
                    path_params={"complaint_id": str(complaint_id)},
                ),
                idempotency_key=uuid4(),
                if_match='"v1"',
                current=proposer,
                db=session,
            )
            assert assignment.status == "APPLIED"

            proposal = await complaint_action(
                complaint_id=complaint_id,
                data=ComplaintAction(
                    action="TEMP_HOLD",
                    reason_code="URGENT_SAFETY_REVIEW",
                    comment="Synthetic moderation case requiring a hold",
                ),
                request=_request(
                    f"/admin/v1/complaints/{complaint_id}/actions",
                    method="POST",
                    path_params={"complaint_id": str(complaint_id)},
                ),
                idempotency_key=uuid4(),
                if_match='"v2"',
                current=proposer,
                db=session,
            )
            operation = await session.get(AdminOperation, proposal.operation_id)
            assert operation is not None
            assert operation.status == "WAITING_APPROVAL"

            operation_path = f"/admin/v1/operations/{operation.id}"
            before_dispatch = await get_operation(
                operation_id=operation.id,
                request=_request(
                    operation_path,
                    path_params={"operation_id": str(operation.id)},
                ),
                response=Response(),
                actor=proposer,
                db=session,
            )
            assert before_dispatch.status == "WAITING_APPROVAL"

            approved = await approve_operation(
                operation_id=operation.id,
                data=ReasonAction(
                    reason_code="URGENT_SAFETY_REVIEW",
                    comment="Independent approval for immediate safety review",
                ),
                request=_request(
                    f"{operation_path}/approve",
                    method="POST",
                    path_params={"operation_id": str(operation.id)},
                ),
                idempotency_key=uuid4(),
                if_match='"1"',
                current=approver,
                db=session,
            )
            assert approved.status == "PARTIAL"

            after_approval = await get_operation(
                operation_id=operation.id,
                request=_request(
                    operation_path,
                    path_params={"operation_id": str(operation.id)},
                ),
                response=Response(),
                actor=proposer,
                db=session,
            )
            assert after_approval.status == "PARTIAL"

            outbox_event = await session.scalar(
                select(ModerationOutboxEvent).where(
                    ModerationOutboxEvent.idempotency_key
                    == f"complaint-action:{operation.id}"
                )
            )
            assert outbox_event is not None
            assert outbox_event.event_type == "COMPLAINT_SAFETY_ACTION"
            assert outbox_event.status == "BLOCKED"
            assert outbox_event.payload["action"] == "TEMP_HOLD"

            complaint = await session.get(Complaint, complaint_id)
            assert complaint is not None
            assert complaint.status == "ESCALATED"
            assert complaint.version == 3
    finally:
        await engine.dispose()
