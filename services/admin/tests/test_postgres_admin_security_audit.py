"""Authentication and authorization denials must persist redacted audit rows."""

import os
from types import SimpleNamespace
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.pool import NullPool
from starlette.requests import Request

from src.api.deps import get_current_moderator, require_permission, verify_service_key
from src.core.config import settings
from src.models.audit_log import AuditLog
from src.services.audit_context import bind_actor_context, bind_request_context, reset_request_context
from src.services.audit_integrity import AuditChainError, verify_audit_chain

pytestmark = pytest.mark.postgres_integration


def _database_url() -> str:
    url = os.getenv("NEOMARKET_ADMIN_POSTGRES_TEST_URL")
    if not url:
        pytest.skip("set NEOMARKET_ADMIN_POSTGRES_TEST_URL to run Admin PostgreSQL integration tests")
    if "+asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


@pytest.mark.asyncio
async def test_postgres_admin_runtime_role_cannot_mutate_audit_logs() -> None:
    runtime_password = os.getenv("ADMIN_RUNTIME_DB_PASSWORD")
    if not runtime_password:
        pytest.skip("set ADMIN_RUNTIME_DB_PASSWORD to test Admin runtime database grants")
    runtime_url = make_url(_database_url()).set(
        username="admin_runtime", password=runtime_password
    )
    engine = create_async_engine(runtime_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            role = (
                await connection.execute(
                    text("SELECT rolsuper, rolcreaterole, rolcreatedb FROM pg_roles WHERE rolname = current_user")
                )
            ).one()
            privileges = (
                await connection.execute(
                    text("""
                        SELECT has_table_privilege(current_user, 'audit_logs', 'SELECT'),
                               has_table_privilege(current_user, 'audit_logs', 'INSERT'),
                               has_table_privilege(current_user, 'audit_logs', 'UPDATE'),
                               has_table_privilege(current_user, 'audit_logs', 'DELETE')
                    """)
                )
            ).one()
        assert tuple(role) == (False, False, False)
        assert tuple(privileges) == (True, True, False, False)

        for statement in (
            "UPDATE audit_logs SET action = action WHERE false",
            "DELETE FROM audit_logs WHERE false",
        ):
            with pytest.raises(DBAPIError):
                async with engine.begin() as connection:
                    await connection.execute(text(statement))
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_audit_chain_verifier_detects_modified_event() -> None:
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    event_id = uuid4()
    try:
        async with AsyncSession(engine) as session:
            session.add(AuditLog(
                id=event_id,
                actor_id=None,
                action="AUDIT_CHAIN_TAMPER_TEST",
                entity_type="test",
                entity_id=event_id,
                details={"original": True},
                created_at=datetime.now(timezone.utc),
                actor_roles=[],
                integrity_version=2,
            ))
            await session.commit()
            sequence_no = await session.scalar(
                select(AuditLog.sequence_no).where(AuditLog.id == event_id)
            )

        async with engine.begin() as connection:
            await connection.execute(text("ALTER TABLE audit_logs DISABLE TRIGGER trg_audit_logs_append_only"))
            await connection.execute(
                text("""
                    UPDATE audit_logs
                       SET details = (details::jsonb || jsonb_build_object('tampered', true))::json
                     WHERE id = :event_id
                """),
                {"event_id": event_id},
            )
            await connection.execute(text("ALTER TABLE audit_logs ENABLE TRIGGER trg_audit_logs_append_only"))

        async with AsyncSession(engine) as session:
            with pytest.raises(
                AuditChainError,
                match=rf"Audit event hash mismatch at {sequence_no}",
            ):
                await verify_audit_chain(session)
    finally:
        await engine.dispose()


def _request(
    method: str,
    path: str,
    request_id: str,
    *,
    path_params: dict[str, str] | None = None,
) -> Request:
    request = Request(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": method,
            "scheme": "https",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [],
            "server": ("admin.test", 443),
            "client": ("127.0.0.1", 12345),
            "root_path": "",
            "path_params": path_params or {},
        }
    )
    request.state.request_id = request_id
    return request


@pytest.mark.asyncio
async def test_postgres_authentication_and_access_denials_are_redacted_and_audited(monkeypatch) -> None:
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "admin_allow_dev_auth", True)
    monkeypatch.setattr(settings, "trusted_service_public_keys", "")
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    try:
        actor_id = uuid4()
        request_id = f"security-audit-{uuid4()}"
        scoped_seller_id = uuid4()
        auth_request = _request("GET", "/admin/v1/moderation/tickets", request_id)
        service_request = _request("POST", "/internal/v1/product-events", request_id)
        access_request = _request("GET", "/admin/v1/taxonomy/categories", request_id)
        scope_request = _request(
            "GET",
            f"/admin/v1/sellers/{scoped_seller_id}",
            request_id,
            path_params={"seller_id": str(scoped_seller_id)},
        )
        step_up_request = _request(
            "POST", f"/admin/v1/products/{uuid4()}/safety-holds", request_id
        )
        context_token = bind_request_context(request_id)

        async with AsyncSession(engine) as session:
            with pytest.raises(HTTPException) as staff_denied:
                await get_current_moderator(request=auth_request, db=session)
            assert staff_denied.value.status_code == 401

            with pytest.raises(HTTPException) as service_denied:
                await verify_service_key(
                    request=service_request,
                    authorization="Bearer deliberately-invalid-token",
                    db=session,
                )
            assert service_denied.value.status_code == 401

            bind_actor_context(actor_id, {"catalog_moderator"})
            actor = SimpleNamespace(
                id=actor_id,
                roles={"catalog_moderator"},
                permissions=set(),
                permission_scopes={},
            )
            with pytest.raises(HTTPException) as access_denied:
                await require_permission("taxonomy.write")(
                    access_request, actor, session
                )
            assert access_denied.value.status_code == 403

            bind_actor_context(actor_id, {"seller_compliance"})
            scoped_actor = SimpleNamespace(
                id=actor_id,
                roles={"seller_compliance"},
                permissions={"sellers.read"},
                permission_scopes={"sellers.read": {f"seller:{uuid4()}"}},
            )
            with pytest.raises(HTTPException) as scope_denied:
                await require_permission("sellers.read")(
                    scope_request, scoped_actor, session
                )
            assert scope_denied.value.status_code == 403

            bind_actor_context(actor_id, {"trust_safety"})
            step_up_actor = SimpleNamespace(
                id=actor_id,
                roles={"trust_safety"},
                permissions={"products.safety_hold"},
                permission_scopes={"products.safety_hold": {"*"}},
                step_up_expires_at=None,
            )
            with pytest.raises(HTTPException) as step_up_denied:
                await require_permission("products.safety_hold")(
                    step_up_request, step_up_actor, session
                )
            assert step_up_denied.value.status_code == 403

        async with AsyncSession(engine) as session:
            rows = (
                await session.scalars(
                    select(AuditLog)
                    .where(
                        AuditLog.action.in_(
                            {"ADMIN_AUTH_FAILED", "ADMIN_ACCESS_DENIED"}
                        ),
                        AuditLog.request_id == request_id,
                    )
                    .order_by(AuditLog.sequence_no)
                )
            ).all()
        assert [row.action for row in rows] == [
            "ADMIN_AUTH_FAILED",
            "ADMIN_AUTH_FAILED",
            "ADMIN_ACCESS_DENIED",
            "ADMIN_ACCESS_DENIED",
            "ADMIN_ACCESS_DENIED",
        ]
        assert rows[0].actor_id is None
        assert rows[0].details == {
            "auth_kind": "staff",
            "method": "GET",
            "path": "/admin/v1/moderation/tickets",
            "status_code": 401,
        }
        assert rows[1].actor_id is None
        assert rows[1].details == {
            "auth_kind": "service",
            "method": "POST",
            "path": "/internal/v1/product-events",
            "status_code": 401,
        }
        assert rows[2].actor_id == actor_id
        assert rows[2].actor_roles == ["catalog_moderator"]
        assert rows[2].details == {
            "method": "GET",
            "path": "/admin/v1/taxonomy/categories",
            "required_permission": "taxonomy.write",
            "status_code": 403,
        }
        assert [row.details["required_permission"] for row in rows[2:]] == [
            "taxonomy.write",
            "sellers.read",
            "products.safety_hold",
        ]
        assert rows[3].details["path"].startswith("/admin/v1/sellers/")
        assert rows[4].details["path"].endswith("/safety-holds")
        assert all(row.actor_id == actor_id for row in rows[2:])
        assert all(row.integrity_hash and row.previous_hash for row in rows)
        async with AsyncSession(engine) as session:
            chain_rows = (
                await session.scalars(
                    select(AuditLog)
                    .where(
                        AuditLog.sequence_no.between(
                            rows[0].sequence_no, rows[-1].sequence_no
                        )
                    )
                    .order_by(AuditLog.sequence_no)
                )
            ).all()
        assert all(
            current.previous_hash == previous.integrity_hash
            for previous, current in zip(chain_rows, chain_rows[1:])
        )
        assert all(
            "deliberately-invalid-token" not in str(row.details) for row in rows
        )
    finally:
        reset_request_context(context_token)
        await engine.dispose()
