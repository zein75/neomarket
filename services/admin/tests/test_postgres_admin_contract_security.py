"""Admin staff response and bulk input contracts backed by PostgreSQL/API routing."""

import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, HTTPException, Response
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.requests import Request

from src.api import deps
from src.api.deps import _authenticate_oidc, _staff_access, require_permission
from src.api.routers import bulk_operations, iam, moderation
from src.api.routers.iam import (
    approve_operation,
    cancel_operation,
    get_operation,
    list_operations,
)
from src.models.admin_operation import AdminOperation
from src.models.moderation_decision_receipt import ModerationDecisionReceipt
from src.models.moderation_outbox_event import ModerationOutboxEvent
from src.models.staff_principal import StaffPrincipal, StaffRoleGrant
from src.schemas.admin import ReasonAction
from src.schemas.admin_responses import StaffProfileResponse

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
    )
    request.state.request_id = str(uuid4())
    return request


async def _actor(session: AsyncSession, role: str) -> SimpleNamespace:
    principal = StaffPrincipal(
        id=uuid4(),
        oidc_issuer="https://issuer.test",
        oidc_subject=f"contract-{role}-{uuid4()}",
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
    )


@pytest.mark.asyncio
async def test_postgres_staff_detail_includes_registered_permissions() -> None:
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            reader = await _actor(session, "security_admin")
            target = await _actor(session, "catalog_moderator")
            request = _request(f"/admin/v1/staff/{target.id}")

            with pytest.raises(HTTPException) as denied:
                await require_permission("iam.read")(
                    request, await _actor(session, "support_viewer"), session
                )
            assert denied.value.status_code == 403

            authorized = await require_permission("iam.read")(request, reader, session)
            payload = await iam.get_staff(
                staff_id=target.id,
                request=request,
                actor=authorized,
                db=session,
            )
            profile = StaffProfileResponse.model_validate(payload)
            assert "permissions" in payload
            assert "moderation.ticket.read" in profile.permissions
            assert "products.read" in profile.permissions
            assert profile.staff_id == target.id
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_oidc_opaque_subject_maps_to_exact_staff_principal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    issuer = "https://issuer.test/tenant"
    audience = "neomarket-admin-test"
    subject = "staff|opaque:subject/7f4b"
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(deps.settings, "oidc_issuer", issuer)
    monkeypatch.setattr(deps.settings, "oidc_jwks_url", f"{issuer}/jwks")
    monkeypatch.setattr(deps.settings, "oidc_audience", audience)
    monkeypatch.setattr(deps.settings, "oidc_required_amr", "mfa")
    monkeypatch.setattr(deps.settings, "oidc_required_acr", "")

    async def oidc_keys(*, required_kid: str | None = None) -> dict[str, object]:
        assert required_kid == "admin-test-key"
        return {"admin-test-key": private_key.public_key()}

    monkeypatch.setattr(deps, "_oidc_keys", oidc_keys)
    token = jwt.encode(
        {
            "iss": issuer,
            "aud": audience,
            "sub": subject,
            "iat": int(now.timestamp()),
            "nbf": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=5)).timestamp()),
            "jti": f"opaque-subject-{uuid4()}",
            "amr": ["pwd", "mfa"],
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "admin-test-key"},
    )
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            expected = StaffPrincipal(
                id=uuid4(), oidc_issuer=issuer, oidc_subject=subject, status="ACTIVE"
            )
            other = StaffPrincipal(
                id=uuid4(),
                oidc_issuer=issuer,
                oidc_subject="staff|different:opaque/subject",
                status="ACTIVE",
            )
            session.add_all((expected, other))
            session.add(StaffRoleGrant(principal_id=expected.id, role="catalog_moderator"))
            session.add(StaffRoleGrant(principal_id=other.id, role="support_viewer"))
            await session.commit()

            authenticated = await _authenticate_oidc(token, session)

            assert authenticated.id == expected.id
            assert authenticated.oidc_issuer == issuer
            assert authenticated.oidc_subject == subject
            assert "moderation.decision.write" in authenticated.permissions
            assert "iam.grant" not in authenticated.permissions

            unknown_subject_token = jwt.encode(
                {
                    "iss": issuer,
                    "aud": audience,
                    "sub": "staff|unknown:subject/does-not-exist",
                    "iat": int(now.timestamp()),
                    "nbf": int(now.timestamp()),
                    "exp": int((now + timedelta(minutes=5)).timestamp()),
                    "jti": f"unknown-subject-{uuid4()}",
                    "amr": ["pwd", "mfa"],
                },
                private_key,
                algorithm="RS256",
                headers={"kid": "admin-test-key"},
            )
            with pytest.raises(HTTPException) as denied:
                await _authenticate_oidc(unknown_subject_token, session)
            assert denied.value.status_code == 403
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_legacy_decision_routes_fail_closed_before_domain_writes() -> None:
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            actor = SimpleNamespace(
                id=uuid4(),
                roles={"catalog_moderator"},
                permissions={"moderation.decision.write"},
                permission_scopes={"moderation.decision.write": {"*"}},
            )
            app = FastAPI()
            app.include_router(moderation.router)

            async def database_session():
                yield session

            app.dependency_overrides[moderation.get_db] = database_session
            app.dependency_overrides[deps.get_current_moderator] = lambda: actor
            ticket_id = uuid4()
            decision_count = await session.scalar(
                select(func.count()).select_from(ModerationDecisionReceipt)
            )
            outbox_count = await session.scalar(
                select(func.count()).select_from(ModerationOutboxEvent)
            )
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="https://admin.test"
            ) as client:
                for path, body in (
                    (f"/api/v1/tickets/{ticket_id}/approve", None),
                    (f"/api/v1/moderation/{ticket_id}/approve", None),
                    (f"/api/v1/products/{ticket_id}/approve", None),
                    (
                        f"/api/v1/tickets/{ticket_id}/block",
                        {
                            "blocking_reason_ids": [str(uuid4())],
                            "comment": "legacy request",
                        },
                    ),
                ):
                    response = await client.post(path, json=body)
                    assert response.status_code == 410, (path, response.text)
                    assert response.json()["detail"]["code"] == "LEGACY_DECISION_DISABLED"

                app.dependency_overrides[deps.get_current_moderator] = lambda: SimpleNamespace(
                    id=uuid4(), roles={"support_viewer"}, permissions=set(), permission_scopes={}
                )
                denied = await client.post(
                    f"/api/v1/tickets/{ticket_id}/block",
                    json={"blocking_reason_ids": [str(uuid4())]},
                )
                assert denied.status_code == 403

            assert await session.scalar(
                select(func.count()).select_from(ModerationDecisionReceipt)
            ) == decision_count
            assert await session.scalar(
                select(func.count()).select_from(ModerationOutboxEvent)
            ) == outbox_count
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_bulk_routes_reject_invalid_selection_contracts_before_provider_call() -> None:
    actor = SimpleNamespace(id=uuid4(), permissions={"bulk.propose"})
    app = FastAPI()
    app.include_router(bulk_operations.router)
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/admin/v1/bulk-operations"
    )
    dependency = next(
        item.call
        for item in route.dependant.dependencies
        if item.name == "_"
    )
    app.dependency_overrides[dependency] = lambda: actor

    first, second = str(uuid4()), str(uuid4())
    invalid_bodies = (
        {"target_ids": [first, first], "action": "ARCHIVE", "reason_code": "DUPLICATE"},
        {"target_ids": [first], "action": "archive", "reason_code": "VALID_REASON"},
        {"target_ids": [first], "action": "ARCHIVE", "reason_code": "invalid"},
        {
            "target_ids": [first, second],
            "action": "ARCHIVE",
            "reason_code": "VALID_REASON",
            "expected_versions": {first: 1},
        },
        {
            "target_ids": [first],
            "action": "ARCHIVE",
            "reason_code": "VALID_REASON",
            "expected_versions": {first: 1, second: 1},
        },
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://admin.test"
    ) as client:
        for body in invalid_bodies:
            response = await client.post(
                "/admin/v1/bulk-operations",
                headers={"Idempotency-Key": str(uuid4())},
                json=body,
            )
            assert response.status_code == 422, response.text

        valid = await client.post(
            "/admin/v1/bulk-operations",
            headers={"Idempotency-Key": str(uuid4())},
            json={
                "target_ids": [first],
                "action": "ARCHIVE",
                "reason_code": "VALID_REASON",
                "expected_versions": {first: 1},
            },
        )
        assert valid.status_code == 503
        assert valid.json()["detail"]["code"] == "NOT_CONFIGURED"


@pytest.mark.asyncio
async def test_postgres_operation_reviewers_can_list_and_poll_only_their_decisions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            requester = await _actor(session, "security_admin")
            approver = await _actor(session, "security_admin")
            canceller = await _actor(session, "operations")
            outsider = await _actor(session, "auditor")
            target = await _actor(session, "support_viewer")
            seller_id = uuid4()
            seller_operation = AdminOperation(
                action="SELLER_RESTRICTION",
                entity_type="seller",
                entity_id=seller_id,
                payload={"expected_version": 1},
                status="WAITING_APPROVAL",
                version=1,
                idempotency_key=str(uuid4()),
                request_hash="a" * 64,
                requested_by=requester.id,
                reason_code="SELLER_REVIEW",
            )
            approved_operation = AdminOperation(
                action="STAFF_SESSION_REVOKE",
                entity_type="staff",
                entity_id=target.id,
                payload={"expected_staff_version": 1},
                status="WAITING_APPROVAL",
                version=1,
                idempotency_key=str(uuid4()),
                request_hash="b" * 64,
                requested_by=requester.id,
                reason_code="SESSION_REVIEW",
            )
            cancelled_operation = AdminOperation(
                action="STAFF_SESSION_REVOKE",
                entity_type="staff",
                entity_id=target.id,
                payload={"expected_staff_version": 1},
                status="WAITING_APPROVAL",
                version=1,
                idempotency_key=str(uuid4()),
                request_hash="c" * 64,
                requested_by=requester.id,
                reason_code="SESSION_REVIEW",
            )
            session.add_all(
                (seller_operation, approved_operation, cancelled_operation)
            )
            await session.commit()

            monkeypatch.setattr(iam, "require_recent_step_up", lambda _actor: None)
            approved = await approve_operation(
                operation_id=approved_operation.id,
                data=ReasonAction(reason_code="SESSION_REVIEW"),
                request=_request(
                    f"/admin/v1/operations/{approved_operation.id}/approve"
                ),
                idempotency_key=uuid4(),
                if_match='"1"',
                current=approver,
                db=session,
            )
            assert approved.status == "APPLIED"

            cancelled = await cancel_operation(
                operation_id=cancelled_operation.id,
                data=ReasonAction(reason_code="SESSION_REVIEW"),
                request=_request(
                    f"/admin/v1/operations/{cancelled_operation.id}/cancel"
                ),
                idempotency_key=uuid4(),
                if_match='"1"',
                current=canceller,
                db=session,
            )
            assert cancelled.status == "CANCELLED"

            for actor, expected_operation in (
                (approver, approved_operation),
                (canceller, cancelled_operation),
            ):
                page = await list_operations(
                    request=_request("/admin/v1/operations"),
                    limit=100,
                    cursor=None,
                    actor=actor,
                    db=session,
                )
                assert any(
                    item["operation_id"] == str(expected_operation.id)
                    for item in page["items"]
                )
                polled = await get_operation(
                    operation_id=expected_operation.id,
                    request=_request(
                        f"/admin/v1/operations/{expected_operation.id}"
                    ),
                    response=Response(),
                    actor=actor,
                    db=session,
                )
                assert polled.status == expected_operation.status

            for operation in (approved_operation, cancelled_operation):
                with pytest.raises(HTTPException) as denied:
                    await get_operation(
                        operation_id=operation.id,
                        request=_request(f"/admin/v1/operations/{operation.id}"),
                        response=Response(),
                        actor=outsider,
                        db=session,
                    )
                assert denied.value.status_code == 404

            seller_reviewer = SimpleNamespace(
                id=uuid4(),
                permissions={"operations.read", "seller.restrict"},
                permission_scopes={
                    "seller.restrict": {f"seller:{uuid4()}"},
                },
            )
            with pytest.raises(HTTPException) as out_of_scope:
                await get_operation(
                    operation_id=seller_operation.id,
                    request=_request(
                        f"/admin/v1/operations/{seller_operation.id}"
                    ),
                    response=Response(),
                    actor=seller_reviewer,
                    db=session,
                )
            assert out_of_scope.value.status_code == 404
    finally:
        await engine.dispose()
