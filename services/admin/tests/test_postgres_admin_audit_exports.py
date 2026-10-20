"""Audit export requests write an immutable audit event with their artifact."""

import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.requests import Request

from src.api.routers.audit_exports import request_audit_export
from src.models.admin_operation import AdminOperation
from src.models.audit_export import AuditExportArtifact
from src.models.audit_log import AuditLog
from src.models.staff_principal import StaffPrincipal
from src.schemas.admin import AuditExportInput
from src.services.audit_context import bind_actor_context, bind_request_context, reset_request_context
from src.services.audit_integrity import verify_audit_chain

pytestmark = pytest.mark.postgres_integration


def _database_url() -> str:
    url = os.getenv("NEOMARKET_ADMIN_POSTGRES_TEST_URL")
    if not url:
        pytest.skip("set NEOMARKET_ADMIN_POSTGRES_TEST_URL to run Admin PostgreSQL integration tests")
    if "+asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


@pytest.mark.asyncio
async def test_postgres_audit_export_request_is_written_to_audit_chain() -> None:
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    actor_id = uuid4()
    request_id = f"audit-export-{uuid4()}"
    now = datetime.now(timezone.utc)
    request = Request({
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": "/admin/v1/audit-events/export",
        "raw_path": b"/admin/v1/audit-events/export",
        "query_string": b"",
        "headers": [],
        "server": ("admin.test", 443),
        "client": ("127.0.0.1", 12345),
        "root_path": "",
        "path_params": {},
    })
    request.state.request_id = request_id
    data = AuditExportInput(
        start_at=now - timedelta(days=1),
        end_at=now + timedelta(seconds=1),
        reason_code="AUDIT_REVIEW",
    )
    context_token = bind_request_context(request_id)
    bind_actor_context(actor_id, {"auditor"})
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            session.add(StaffPrincipal(
                id=actor_id,
                oidc_issuer="https://issuer.test",
                oidc_subject=f"audit-export-{actor_id}",
                status="ACTIVE",
            ))
            await session.commit()

        async with AsyncSession(engine, expire_on_commit=False) as session:
            response = await request_audit_export(
                data=data,
                request=request,
                idempotency_key=uuid4(),
                actor=SimpleNamespace(id=actor_id),
                db=session,
            )
            assert response.status == "APPLIED"
            export_id = response.resource_id

        async with AsyncSession(engine) as session:
            artifact = await session.get(AuditExportArtifact, export_id)
            operation = await session.scalar(select(AdminOperation).where(
                AdminOperation.action == "AUDIT_EXPORT",
                AdminOperation.entity_id == export_id,
            ))
            audit = await session.scalar(select(AuditLog).where(
                AuditLog.action == "AUDIT_EXPORT_CREATED",
                AuditLog.entity_id == export_id,
            ))
            chain = await verify_audit_chain(session)

        assert artifact is not None and artifact.requested_by == actor_id
        assert operation is not None and operation.requested_by == actor_id
        assert audit is not None and audit.actor_id == actor_id
        assert audit.request_id == request_id
        assert audit.reason_code == "AUDIT_REVIEW"
        assert audit.details["sha256"] == artifact.sha256 == operation.payload["sha256"]
        assert chain["valid_events"] == 1
    finally:
        reset_request_context(context_token)
        await engine.dispose()
