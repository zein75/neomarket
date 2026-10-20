"""Blocking reason lifecycle is versioned, approved, and archived in place."""

import os
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.requests import Request

from src.api.routers.iam import approve_operation
from src.api.routers.policy_reasons import archive_reason, create_reason, update_reason
from src.models.moderation import BlockingReason
from src.models.staff_principal import StaffPrincipal
from src.schemas.admin import ReasonAction, ReasonInput

pytestmark = pytest.mark.postgres_integration


def _database_url() -> str:
    url = os.getenv("NEOMARKET_ADMIN_POSTGRES_TEST_URL")
    if not url:
        pytest.skip("set NEOMARKET_ADMIN_POSTGRES_TEST_URL to run Admin PostgreSQL integration tests")
    return url.replace("postgresql://", "postgresql+asyncpg://", 1) if "+asyncpg" not in url else url


def _request(path: str, method: str = "POST") -> Request:
    raw_path = path.encode()
    request = Request({
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": "https",
        "path": path,
        "raw_path": raw_path,
        "query_string": b"",
        "headers": [],
        "server": ("admin.test", 443),
        "client": ("127.0.0.1", 12345),
        "root_path": "",
        "path_params": {},
    })
    request.state.request_id = str(uuid4())
    return request


def _actor() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        permissions={"policy.reason.write", "operations.approve", "*"},
        permission_scopes={},
        mfa_verified=True,
        step_up_verified=True,
        roles={"senior_moderator"},
    )


async def _approve(session: AsyncSession, operation_id: UUID, checker: SimpleNamespace) -> None:
    result = await approve_operation(
        operation_id,
        ReasonAction(reason_code="POLICY_REASON_CHANGE"),
        _request(f"/admin/v1/operations/{operation_id}/approve"),
        uuid4(),
        '"1"',
        checker,
        session,
    )
    assert result.status == "APPLIED"


@pytest.mark.asyncio
async def test_postgres_blocking_reason_create_update_archive_is_versioned_and_soft_deleted() -> None:
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    maker, checker = _actor(), _actor()
    reason_id: UUID | None = None
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            session.add_all(
                StaffPrincipal(
                    id=principal.id,
                    oidc_issuer="https://issuer.test",
                    oidc_subject=f"policy-reason-{principal.id}",
                    status="ACTIVE",
                )
                for principal in (maker, checker)
            )
            await session.flush()
            created = await create_reason(
                ReasonInput(code="TEST_POLICY_REASON", title="Initial title", description="Initial description", severity="REJECT"),
                _request("/admin/v1/blocking-reasons"),
                uuid4(),
                maker,
                session,
            )
            reason_id = created.resource_id
            await _approve(session, created.operation_id, checker)

            reason = await session.get(BlockingReason, reason_id)
            assert reason is not None
            assert reason.is_active is True
            assert reason.version == 1

            updated = await update_reason(
                reason_id,
                ReasonInput(code="TEST_POLICY_REASON", title="Updated title", description="Updated description", severity="HARD_BLOCK"),
                _request(f"/admin/v1/blocking-reasons/{reason_id}", "PATCH"),
                uuid4(),
                '"1"',
                maker,
                session,
            )
            await _approve(session, updated.operation_id, checker)
            await session.refresh(reason)
            assert reason.title == "Updated title"
            assert reason.severity == "HARD_BLOCK"
            assert reason.hard_block is True
            assert reason.version == 2

            archived = await archive_reason(
                reason_id,
                ReasonAction(reason_code="POLICY_REASON_CHANGE", comment="Retired by policy owner"),
                _request(f"/admin/v1/blocking-reasons/{reason_id}/archive"),
                uuid4(),
                '"2"',
                maker,
                session,
            )
            await _approve(session, archived.operation_id, checker)
            await session.refresh(reason)
            assert reason.is_active is False
            assert reason.version == 3
            assert await session.scalar(select(BlockingReason.id).where(BlockingReason.id == reason_id)) == reason_id
    finally:
        await engine.dispose()
