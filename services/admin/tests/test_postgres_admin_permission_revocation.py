"""A persisted Admin web session must observe permission revocation immediately."""

import hashlib
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool
from shared.utils.request_id import RequestIdMiddleware

from src.api import deps
from src.api.routers import iam, moderation
from src.models.admin_operation import AdminOperation
from src.models.admin_web_session import AdminWebSession
from src.models.audit_log import AuditLog
from src.models.staff_principal import StaffPrincipal, StaffRoleGrant
from src.services.audit_integrity import verify_audit_chain

pytestmark = pytest.mark.postgres_integration


def _database_url() -> str:
    url = os.getenv("NEOMARKET_ADMIN_POSTGRES_TEST_URL")
    if not url:
        pytest.skip("set NEOMARKET_ADMIN_POSTGRES_TEST_URL to run Admin PostgreSQL integration tests")
    if "+asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


def _session(principal_id, token: str, csrf_token: str, now: datetime) -> AdminWebSession:
    return AdminWebSession(
        principal_id=principal_id,
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        csrf_hash=hashlib.sha256(csrf_token.encode()).hexdigest(),
        created_at=now,
        last_seen_at=now,
        idle_expires_at=now + timedelta(hours=1),
        absolute_expires_at=now + timedelta(hours=8),
        step_up_expires_at=now + timedelta(minutes=5),
    )


@pytest.mark.asyncio
async def test_postgres_approved_permission_revocation_applies_to_existing_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(deps.settings, "admin_public_origin", "https://admin.test")
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            now = datetime.now(timezone.utc)
            requester = StaffPrincipal(
                id=uuid4(), oidc_issuer="https://issuer.test", oidc_subject=f"revoke-requester-{uuid4()}", status="ACTIVE"
            )
            approver = StaffPrincipal(
                id=uuid4(), oidc_issuer="https://issuer.test", oidc_subject=f"revoke-approver-{uuid4()}", status="ACTIVE"
            )
            target = StaffPrincipal(
                id=uuid4(), oidc_issuer="https://issuer.test", oidc_subject=f"revoke-target-{uuid4()}", status="ACTIVE"
            )
            grant = StaffRoleGrant(
                principal_id=target.id,
                role="permission:moderation.ticket.read",
                scope_key="global",
                granted_by=requester.id,
            )
            tokens = {principal.id: f"opaque-{uuid4()}" for principal in (requester, approver, target)}
            csrf_tokens = {principal.id: f"csrf-{uuid4()}" for principal in (requester, approver, target)}
            session.add_all([requester, approver, target])
            await session.flush()
            session.add_all(
                [
                    grant,
                    StaffRoleGrant(principal_id=requester.id, role="security_admin", scope_key="global"),
                    StaffRoleGrant(principal_id=approver.id, role="security_admin", scope_key="global"),
                    *[
                        _session(principal.id, tokens[principal.id], csrf_tokens[principal.id], now)
                        for principal in (requester, approver, target)
                    ],
                ]
            )
            await session.commit()

            async def database_session() -> AsyncSession:
                return session

            app = FastAPI()
            app.add_middleware(RequestIdMiddleware)
            app.include_router(iam.router)
            app.include_router(moderation.router)
            app.dependency_overrides[deps.get_db] = database_session

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="https://admin.test"
            ) as client:
                async def use_session(principal_id, *, csrf: bool = False):
                    client.cookies.set("__Host-nm_admin_access", tokens[principal_id])
                    client.cookies.set("__Host-nm_admin_csrf", csrf_tokens[principal_id])
                    headers = {}
                    if csrf:
                        headers = {
                            "Origin": "https://admin.test",
                            "Sec-Fetch-Site": "same-origin",
                            "X-CSRF-Token": csrf_tokens[principal_id],
                        }
                    return headers

                target_headers = await use_session(target.id)
                first_access = await client.get(
                    "/admin/v1/moderation/tickets", headers=target_headers
                )
                assert first_access.status_code == 200
                assert first_access.json()["items"] == []

                requester_headers = await use_session(requester.id, csrf=True)
                proposed = await client.post(
                    f"/admin/v1/staff/{target.id}/grants/{grant.id}/revoke",
                    headers={
                        **requester_headers,
                        "Idempotency-Key": str(uuid4()),
                        "If-Match": '"1"',
                    },
                    json={"reason_code": "ACCESS_REVIEW"},
                )
                assert proposed.status_code == 202, proposed.text
                operation = await session.get(AdminOperation, proposed.json()["operation_id"])
                assert operation is not None
                assert operation.status == "WAITING_APPROVAL"

                approver_headers = await use_session(approver.id, csrf=True)
                approved = await client.post(
                    f"/admin/v1/operations/{operation.id}/approve",
                    headers={
                        **approver_headers,
                        "Idempotency-Key": str(uuid4()),
                        "If-Match": '"1"',
                    },
                    json={"reason_code": "ACCESS_REVIEW"},
                )
                assert approved.status_code == 202, approved.text

                await session.refresh(grant)
                await session.refresh(target)
                assert grant.expires_at is not None
                assert grant.expires_at <= datetime.now(timezone.utc)
                assert target.status == "ACTIVE"

                target_headers = await use_session(target.id)
                after_revocation = await client.get(
                    "/admin/v1/moderation/tickets", headers=target_headers
                )
                assert after_revocation.status_code == 403

            persisted_session = await session.scalar(
                select(AdminWebSession).where(
                    AdminWebSession.principal_id == target.id,
                    AdminWebSession.token_hash == hashlib.sha256(tokens[target.id].encode()).hexdigest(),
                )
            )
            assert persisted_session is not None
            assert persisted_session.revoked_at is None
            auth_failure = await session.scalar(
                select(AuditLog)
                .where(
                    AuditLog.action == "ADMIN_AUTH_FAILED",
                    AuditLog.details["path"].as_string() == "/admin/v1/moderation/tickets",
                    AuditLog.details["status_code"].as_integer() == 403,
                )
                .order_by(AuditLog.created_at.desc())
            )
            assert auth_failure is not None
            role_change_events = (
                await session.scalars(
                    select(AuditLog)
                    .where(
                        AuditLog.action.in_(
                            [
                                "STAFF_PERMISSION_REVOKE_PROPOSED",
                                "STAFF_PERMISSION_REVOKE_APPROVED",
                            ]
                        ),
                        AuditLog.entity_type == "staff",
                        AuditLog.entity_id == target.id,
                    )
                    .order_by(AuditLog.sequence_no)
                )
            ).all()
            assert [event.action for event in role_change_events] == [
                "STAFF_PERMISSION_REVOKE_PROPOSED",
                "STAFF_PERMISSION_REVOKE_APPROVED",
            ]
            proposal_audit, approval_audit = role_change_events
            assert proposal_audit.actor_id == requester.id
            assert approval_audit.actor_id == approver.id
            assert proposal_audit.details["permission"] == "moderation.ticket.read"
            assert proposal_audit.details["scope"] == "global"
            assert proposal_audit.details["reason_code"] == "ACCESS_REVIEW"
            assert approval_audit.details["requested_by"] == str(requester.id)
            assert approval_audit.details["permission"] == "moderation.ticket.read"
            assert approval_audit.details["scope"] == "global"
            assert approval_audit.details["reason_code"] == "ACCESS_REVIEW"
            chain = await verify_audit_chain(session)
            persisted_audit_count = await session.scalar(
                select(func.count()).select_from(AuditLog)
            )
            assert chain["valid_events"] == persisted_audit_count
    finally:
        await engine.dispose()
