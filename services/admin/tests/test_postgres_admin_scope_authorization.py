"""Role grants and object scopes must fail closed on real PostgreSQL."""

import hashlib
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.requests import Request

from src.api import deps
from src.api.deps import ROLE_PERMISSIONS, _staff_access, authorize_permission_scope
from src.api.deps import require_permission
from src.api.routers import iam, moderation, taxonomy
from src.models.admin_operation import AdminOperation
from src.models.audit_log import AuditLog
from src.models.moderation import ModerationCard, ModerationStatus
from src.models.moderation_outbox_event import ModerationOutboxEvent
from src.models.staff_principal import StaffPrincipal, StaffRoleGrant
from src.schemas.admin import ReasonAction
from src.services.audit_context import bind_actor_context
from src.services.audit_integrity import verify_audit_chain

pytestmark = pytest.mark.postgres_integration


def _database_url() -> str:
    url = os.getenv("NEOMARKET_ADMIN_POSTGRES_TEST_URL")
    if not url:
        pytest.skip("set NEOMARKET_ADMIN_POSTGRES_TEST_URL to run Admin PostgreSQL integration tests")
    if "+asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


def _request_for_ticket(ticket_id: str) -> Request:
    path = f"/admin/v1/moderation/tickets/{ticket_id}"
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
        "path_params": {"ticket_id": ticket_id},
    }
    return Request(scope)


def _request(path: str, *, method: str = "GET") -> Request:
    scope = {
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
        "path_params": {},
    }
    return Request(scope)


@pytest.mark.asyncio
async def test_postgres_seller_scope_allows_own_ticket_and_denies_foreign_ticket() -> None:
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    try:
        principal_id, seller_id, other_seller_id = uuid4(), uuid4(), uuid4()
        ticket_id = uuid4()
        region_principal_id, expired_principal_id = uuid4(), uuid4()
        now = datetime.now(timezone.utc)
        async with AsyncSession(engine) as session, session.begin():
            session.add_all(
                [
                    StaffPrincipal(
                        id=principal_id,
                        oidc_issuer="https://issuer.test",
                        oidc_subject=f"seller-scope-{principal_id}",
                        status="ACTIVE",
                    ),
                    StaffPrincipal(
                        id=region_principal_id,
                        oidc_issuer="https://issuer.test",
                        oidc_subject=f"region-scope-{region_principal_id}",
                        status="ACTIVE",
                    ),
                    StaffPrincipal(
                        id=expired_principal_id,
                        oidc_issuer="https://issuer.test",
                        oidc_subject=f"expired-scope-{expired_principal_id}",
                        status="ACTIVE",
                    ),
                    ModerationCard(
                        id=ticket_id,
                        product_id=uuid4(),
                        seller_id=seller_id,
                        kind="CREATE",
                        status=ModerationStatus.PENDING,
                    ),
                    StaffRoleGrant(
                        principal_id=principal_id,
                        role="catalog_moderator",
                        scope_key=f"seller:{seller_id}",
                    ),
                    StaffRoleGrant(
                        principal_id=region_principal_id,
                        role="catalog_moderator",
                        scope_key="region:ru",
                    ),
                    StaffRoleGrant(
                        principal_id=expired_principal_id,
                        role="catalog_moderator",
                        scope_key="global",
                        expires_at=now - timedelta(seconds=1),
                    ),
                ]
            )

        async with AsyncSession(engine) as session:
            principal = StaffPrincipal(id=principal_id, oidc_issuer="", oidc_subject="")
            roles, permissions, scopes = await _staff_access(principal, session, now)
            assert "catalog_moderator" in roles
            assert "moderation.ticket.read" in permissions
            assert scopes["moderation.ticket.read"] == {f"seller:{seller_id}"}
            assert "taxonomy.write" not in permissions
            actor = SimpleNamespace(
                permissions=permissions,
                permission_scopes=scopes,
            )
            await authorize_permission_scope(
                "moderation.ticket.read", _request_for_ticket(str(ticket_id)), actor, session
            )

            foreign_card_id = uuid4()
            session.add(
                ModerationCard(
                    id=foreign_card_id,
                    product_id=uuid4(),
                    seller_id=other_seller_id,
                    kind="CREATE",
                    status=ModerationStatus.PENDING,
                )
            )
            await session.flush()
            with pytest.raises(HTTPException) as denied:
                await authorize_permission_scope(
                    "moderation.ticket.read",
                    _request_for_ticket(str(foreign_card_id)),
                    actor,
                    session,
                )
            assert denied.value.status_code == 403
            assert denied.value.detail["code"] == "SCOPE_DENIED"

            with pytest.raises(HTTPException) as unknown_scope:
                await _staff_access(
                    StaffPrincipal(id=region_principal_id, oidc_issuer="", oidc_subject=""),
                    session,
                    now,
                )
            assert unknown_scope.value.status_code == 403

            with pytest.raises(HTTPException) as expired:
                await _staff_access(
                    StaffPrincipal(id=expired_principal_id, oidc_issuer="", oidc_subject=""),
                    session,
                    now,
                )
            assert expired.value.status_code == 403
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_seller_scope_filters_moderation_api_and_denies_foreign_ids() -> None:
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    try:
        principal_id, seller_id, foreign_seller_id = uuid4(), uuid4(), uuid4()
        owned_ticket_id, foreign_ticket_id = uuid4(), uuid4()
        async with AsyncSession(engine, expire_on_commit=False) as session:
            principal = StaffPrincipal(
                id=principal_id,
                oidc_issuer="https://issuer.test",
                oidc_subject=f"seller-scope-api-{principal_id}",
                status="ACTIVE",
            )
            session.add_all(
                [
                    principal,
                    StaffRoleGrant(
                        principal_id=principal_id,
                        role="catalog_moderator",
                        scope_key=f"seller:{seller_id}",
                    ),
                    ModerationCard(
                        id=owned_ticket_id,
                        product_id=uuid4(),
                        seller_id=seller_id,
                        kind="CREATE",
                        status=ModerationStatus.PENDING,
                        submitted_revision=1,
                        snapshot_hash="a" * 64,
                    ),
                    ModerationCard(
                        id=foreign_ticket_id,
                        product_id=uuid4(),
                        seller_id=foreign_seller_id,
                        kind="CREATE",
                        status=ModerationStatus.PENDING,
                        submitted_revision=1,
                        snapshot_hash="b" * 64,
                    ),
                ]
            )
            await session.commit()

            roles, permissions, scopes = await _staff_access(
                principal, session, datetime.now(timezone.utc)
            )
            actor = SimpleNamespace(
                id=principal_id,
                roles=roles,
                permissions=permissions,
                permission_scopes=scopes,
            )
            assert scopes["moderation.ticket.read"] == {f"seller:{seller_id}"}

            async def current_actor() -> SimpleNamespace:
                bind_actor_context(actor.id, actor.roles)
                return actor

            async def database_session() -> AsyncSession:
                return session

            app = FastAPI()
            app.include_router(moderation.router)
            app.dependency_overrides[deps.get_current_moderator] = current_actor
            app.dependency_overrides[deps.get_db] = database_session
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="https://admin.test"
            ) as client:
                queue = await client.get("/admin/v1/moderation/tickets")
                assert queue.status_code == 200
                assert [item["id"] for item in queue.json()["items"]] == [
                    str(owned_ticket_id)
                ]

                own_detail = await client.get(
                    f"/admin/v1/moderation/tickets/{owned_ticket_id}"
                )
                assert own_detail.status_code == 409
                assert own_detail.json()["detail"]["code"] == "REVALIDATION_REQUIRED"

                foreign_detail = await client.get(
                    f"/admin/v1/moderation/tickets/{foreign_ticket_id}"
                )
                assert foreign_detail.status_code == 403
                assert foreign_detail.json()["detail"]["code"] == "SCOPE_DENIED"

                foreign_filter = await client.get(
                    "/admin/v1/moderation/tickets",
                    params={"seller_id": str(foreign_seller_id)},
                )
                assert foreign_filter.status_code == 403
                assert foreign_filter.json()["detail"]["code"] == "SCOPE_DENIED"

            denials = (
                await session.scalars(
                    select(AuditLog).where(
                        AuditLog.action == "ADMIN_ACCESS_DENIED",
                        AuditLog.actor_id == principal_id,
                        AuditLog.details["required_permission"].as_string()
                        == "moderation.ticket.read",
                    )
                )
            ).all()
            assert len(denials) == 2
            assert {
                event.details["path"] for event in denials
            } == {
                f"/admin/v1/moderation/tickets/{foreign_ticket_id}",
                "/admin/v1/moderation/tickets",
            }
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_catalog_moderator_cannot_propose_category_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            principal = StaffPrincipal(
                id=uuid4(),
                oidc_issuer="https://issuer.test",
                oidc_subject=f"taxonomy-denied-{uuid4()}",
                status="ACTIVE",
            )
            session.add(principal)
            session.add(
                StaffRoleGrant(
                    principal_id=principal.id,
                    role="catalog_moderator",
                    scope_key="global",
                )
            )
            await session.commit()

            roles, permissions, scopes = await _staff_access(
                principal, session, datetime.now(timezone.utc)
            )
            assert "taxonomy.category.write" not in permissions
            actor = SimpleNamespace(
                id=principal.id,
                roles=roles,
                permissions=permissions,
                permission_scopes=scopes,
                step_up_expires_at=None,
            )
            operation_count_before = await session.scalar(
                select(func.count()).select_from(AdminOperation)
            )
            audit_count_before = await session.scalar(
                select(func.count()).select_from(AuditLog)
            )

            async def forbidden_b2b_call() -> dict[str, object]:
                raise AssertionError("taxonomy mutation reached B2B after permission denial")

            async def current_actor() -> SimpleNamespace:
                bind_actor_context(actor.id, actor.roles)
                return actor

            async def database_session() -> AsyncSession:
                return session

            app = FastAPI()
            app.include_router(taxonomy.router)
            app.dependency_overrides[deps.get_current_moderator] = current_actor
            app.dependency_overrides[deps.get_db] = database_session
            monkeypatch.setattr(taxonomy, "_snapshot", forbidden_b2b_call)
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="https://admin.test"
            ) as client:
                response = await client.post(
                    "/admin/v1/taxonomy/categories",
                    headers={"Idempotency-Key": str(uuid4())},
                    json={"code": "blocked", "slug": "blocked", "name": "Blocked"},
                )

            assert response.status_code == 403
            assert response.json()["detail"]["code"] == "PERMISSION_DENIED"
            assert await session.scalar(
                select(func.count()).select_from(AdminOperation)
            ) == operation_count_before
            assert await session.scalar(
                select(func.count()).select_from(AuditLog)
            ) == audit_count_before + 1
            denied = await session.scalar(
                select(AuditLog)
                .where(
                    AuditLog.action == "ADMIN_ACCESS_DENIED",
                    AuditLog.details["path"].as_string()
                    == "/admin/v1/taxonomy/categories",
                    AuditLog.details["required_permission"].as_string()
                    == "taxonomy.category.write",
                )
                .order_by(AuditLog.created_at.desc())
            )
            assert denied is not None
            assert denied.details["status_code"] == 403
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_auditor_cannot_mutate_taxonomy() -> None:
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    try:
        assert ROLE_PERMISSIONS["auditor"] == frozenset(
            {"session.read", "session.revoke", "audit.read", "audit.export", "operations.read"}
        )
        async with AsyncSession(engine, expire_on_commit=False) as session:
            principal = StaffPrincipal(
                id=uuid4(),
                oidc_issuer="https://issuer.test",
                oidc_subject=f"auditor-read-only-{uuid4()}",
                status="ACTIVE",
            )
            session.add(principal)
            session.add(
                StaffRoleGrant(
                    principal_id=principal.id,
                    role="auditor",
                    scope_key="global",
                )
            )
            await session.commit()

            roles, permissions, scopes = await _staff_access(
                principal, session, datetime.now(timezone.utc)
            )
            actor = SimpleNamespace(
                id=principal.id,
                roles=roles,
                permissions=permissions,
                permission_scopes=scopes,
                step_up_expires_at=None,
            )
            operation_count_before = await session.scalar(
                select(func.count()).select_from(AdminOperation)
            )
            audit_count_before = await session.scalar(
                select(func.count()).select_from(AuditLog)
            )

            async def current_actor() -> SimpleNamespace:
                bind_actor_context(actor.id, actor.roles)
                return actor

            async def database_session() -> AsyncSession:
                return session

            app = FastAPI()
            app.include_router(taxonomy.router)
            app.dependency_overrides[deps.get_current_moderator] = current_actor
            app.dependency_overrides[deps.get_db] = database_session
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="https://admin.test"
            ) as client:
                response = await client.post(
                    "/admin/v1/taxonomy/categories",
                    headers={"Idempotency-Key": str(uuid4())},
                    json={"code": "auditor-blocked", "slug": "auditor-blocked", "name": "Blocked"},
                )

            assert response.status_code == 403
            assert response.json()["detail"]["code"] == "PERMISSION_DENIED"
            assert await session.scalar(
                select(func.count()).select_from(AdminOperation)
            ) == operation_count_before
            assert await session.scalar(
                select(func.count()).select_from(AuditLog)
            ) == audit_count_before + 1
            denied = await session.scalar(
                select(AuditLog)
                .where(
                    AuditLog.action == "ADMIN_ACCESS_DENIED",
                    AuditLog.actor_id == principal.id,
                    AuditLog.details["path"].as_string()
                    == "/admin/v1/taxonomy/categories",
                    AuditLog.details["required_permission"].as_string()
                    == "taxonomy.category.write",
                )
                .order_by(AuditLog.created_at.desc())
            )
            assert denied is not None
            assert denied.details["status_code"] == 403
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_low_privilege_support_cannot_export_audit() -> None:
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    try:
        principal_id = uuid4()
        now = datetime.now(timezone.utc)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            principal = StaffPrincipal(
                id=principal_id,
                oidc_issuer="https://issuer.test",
                oidc_subject=f"support-export-denied-{principal_id}",
                status="ACTIVE",
            )
            session.add(principal)
            session.add(StaffRoleGrant(
                principal_id=principal_id,
                role="support_viewer",
                scope_key="global",
            ))
            await session.commit()
            roles, permissions, scopes = await _staff_access(principal, session, now)
            operation_count_before = await session.scalar(
                select(func.count()).select_from(AdminOperation)
            )
            actor = SimpleNamespace(
                id=principal_id,
                roles=roles,
                permissions=permissions,
                permission_scopes=scopes,
            )
            bind_actor_context(principal_id, roles)
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
            with pytest.raises(HTTPException) as denied:
                await require_permission("audit.export")(request, actor, session)
            assert denied.value.status_code == 403
            assert denied.value.detail["code"] == "PERMISSION_DENIED"
            assert await session.scalar(select(func.count()).select_from(AdminOperation)) == operation_count_before
            denial = await session.scalar(select(AuditLog).where(
                AuditLog.actor_id == principal_id,
                AuditLog.action == "ADMIN_ACCESS_DENIED",
            ).order_by(AuditLog.created_at.desc()))
            assert denial is not None
            assert denial.details["required_permission"] == "audit.export"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_only_senior_moderator_can_hard_block_via_api() -> None:
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            standard = StaffPrincipal(
                id=uuid4(),
                oidc_issuer="https://issuer.test",
                oidc_subject=f"hard-block-standard-{uuid4()}",
                status="ACTIVE",
            )
            senior = StaffPrincipal(
                id=uuid4(),
                oidc_issuer="https://issuer.test",
                oidc_subject=f"hard-block-senior-{uuid4()}",
                status="ACTIVE",
            )
            session.add_all(
                [
                    standard,
                    senior,
                    StaffRoleGrant(
                        principal_id=standard.id,
                        role="catalog_moderator",
                        scope_key="global",
                    ),
                    StaffRoleGrant(
                        principal_id=senior.id,
                        role="senior_moderator",
                        scope_key="global",
                    ),
                ]
            )
            await session.commit()

            standard_roles, standard_permissions, standard_scopes = await _staff_access(
                standard, session, datetime.now(timezone.utc)
            )
            senior_roles, senior_permissions, senior_scopes = await _staff_access(
                senior, session, datetime.now(timezone.utc)
            )
            assert "moderation.decision.write" in standard_permissions
            assert "moderation.hard_block" not in standard_permissions
            assert "moderation.hard_block" in senior_permissions
            assert "moderation.hard_block" not in ROLE_PERMISSIONS["trust_safety"]

            actors = {
                standard.id: SimpleNamespace(
                    id=standard.id,
                    roles=standard_roles,
                    permissions=standard_permissions,
                    permission_scopes=standard_scopes,
                    step_up_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
                ),
                senior.id: SimpleNamespace(
                    id=senior.id,
                    roles=senior_roles,
                    permissions=senior_permissions,
                    permission_scopes=senior_scopes,
                    step_up_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
                ),
            }
            active_actor = actors[standard.id]

            async def current_actor() -> SimpleNamespace:
                bind_actor_context(active_actor.id, active_actor.roles)
                return active_actor

            async def database_session() -> AsyncSession:
                return session

            app = FastAPI()
            app.include_router(moderation.router)
            app.dependency_overrides[deps.get_current_moderator] = current_actor
            app.dependency_overrides[deps.get_db] = database_session
            missing_ticket_id = uuid4()
            body = {
                "action": "HARD_BLOCK",
                "claim_token": "claim-token-" + "a" * 48,
                "product_revision": 1,
                "snapshot_hash": "b" * 64,
                "reason_codes": ["POLICY_VIOLATION"],
                "passed_rules": [],
                "field_reports": [
                    {
                        "field_path": "title",
                        "reason_code": "POLICY_VIOLATION",
                        "comment": "This listing is prohibited.",
                    }
                ],
                "comment": "This listing violates the prohibited goods policy.",
                "policy_version": 1,
            }
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="https://admin.test"
            ) as client:
                denied = await client.post(
                    f"/admin/v1/moderation/tickets/{missing_ticket_id}/decisions",
                    headers={"Idempotency-Key": str(uuid4()), "If-Match": '"1"'},
                    json=body,
                )
                assert denied.status_code == 403
                assert denied.json()["detail"]["code"] == "PERMISSION_DENIED"

                active_actor = actors[senior.id]
                senior_request = await client.post(
                    f"/admin/v1/moderation/tickets/{missing_ticket_id}/decisions",
                    headers={"Idempotency-Key": str(uuid4()), "If-Match": '"1"'},
                    json=body,
                )
                assert senior_request.status_code == 404
                assert senior_request.json()["detail"]["code"] == "TICKET_NOT_FOUND"

            access_denial = await session.scalar(
                select(AuditLog)
                .where(
                    AuditLog.action == "ADMIN_ACCESS_DENIED",
                    AuditLog.actor_id == standard.id,
                    AuditLog.details["required_permission"].as_string()
                    == "moderation.hard_block",
                )
                .order_by(AuditLog.created_at.desc())
            )
            assert access_denial is not None
            assert access_denial.details["status_code"] == 403
            assert access_denial.actor_roles == ["catalog_moderator"]
            assert await session.scalar(
                select(func.count())
                .select_from(AdminOperation)
                .where(AdminOperation.requested_by.in_((standard.id, senior.id)))
            ) == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_taxonomy_proposer_cannot_approve_own_category_operation() -> None:
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            principal = StaffPrincipal(
                id=uuid4(),
                oidc_issuer="https://issuer.test",
                oidc_subject=f"taxonomy-maker-checker-{uuid4()}",
                status="ACTIVE",
            )
            session.add(principal)
            session.add_all(
                [
                    StaffRoleGrant(
                        principal_id=principal.id,
                        role="taxonomy_editor",
                        scope_key="global",
                    ),
                    StaffRoleGrant(
                        principal_id=principal.id,
                        role="taxonomy_approver",
                        scope_key="global",
                    ),
                ]
            )
            await session.flush()
            operation = AdminOperation(
                id=uuid4(),
                action="CATEGORY_CREATE",
                entity_type="category",
                entity_id=uuid4(),
                payload={"code": "maker-checker-category", "slug": "maker-checker-category"},
                status="WAITING_APPROVAL",
                version=1,
                idempotency_key=str(uuid4()),
                request_hash=hashlib.sha256(b"category proposal").hexdigest(),
                requested_by=principal.id,
                reason_code="TAXONOMY_CHANGE",
            )
            session.add(operation)
            await session.commit()

            roles, permissions, scopes = await _staff_access(
                principal, session, datetime.now(timezone.utc)
            )
            assert "taxonomy.category.write" in permissions
            assert "taxonomy.category.publish" in permissions
            actor = SimpleNamespace(
                id=principal.id,
                roles=roles,
                permissions=permissions,
                permission_scopes=scopes,
                step_up_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            )
            audit_count_before = await session.scalar(
                select(func.count()).select_from(AuditLog)
            )

            async def current_actor() -> SimpleNamespace:
                bind_actor_context(actor.id, actor.roles)
                return actor

            async def database_session() -> AsyncSession:
                return session

            app = FastAPI()
            app.include_router(iam.router)
            app.dependency_overrides[deps.get_current_moderator] = current_actor
            app.dependency_overrides[deps.get_db] = database_session
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="https://admin.test"
            ) as client:
                response = await client.post(
                    f"/admin/v1/operations/{operation.id}/approve",
                    headers={
                        "Idempotency-Key": str(uuid4()),
                        "If-Match": '"1"',
                    },
                    json={"reason_code": "TAXONOMY_CHANGE"},
                )

            assert response.status_code == 403
            assert response.json()["detail"]["code"] == "MAKER_CHECKER_VIOLATION"
            await session.refresh(operation)
            assert operation.status == "WAITING_APPROVAL"
            assert operation.approved_by is None
            assert operation.approval_key is None
            assert await session.scalar(
                select(func.count()).select_from(AuditLog)
            ) == audit_count_before + 1
            audit = await session.scalar(
                select(AuditLog)
                .where(
                    AuditLog.action == "ADMIN_MAKER_CHECKER_VIOLATION",
                    AuditLog.entity_id == operation.id,
                )
                .order_by(AuditLog.created_at.desc())
            )
            assert audit is not None
            assert audit.actor_id == principal.id
            assert set(audit.actor_roles or []) == {"taxonomy_editor", "taxonomy_approver"}
            assert audit.details == {"action": "CATEGORY_CREATE", "status_code": 403}
            chain = await verify_audit_chain(session)
            assert chain["valid_events"] == audit_count_before + 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_independent_operation_approval_is_version_and_idempotency_bound() -> None:
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            requester = StaffPrincipal(
                id=uuid4(),
                oidc_issuer="https://issuer.test",
                oidc_subject=f"operation-requester-{uuid4()}",
                status="ACTIVE",
            )
            approver = StaffPrincipal(
                id=uuid4(),
                oidc_issuer="https://issuer.test",
                oidc_subject=f"operation-approver-{uuid4()}",
                status="ACTIVE",
            )
            session.add_all([requester, approver])
            await session.flush()
            operation = AdminOperation(
                id=uuid4(),
                action="CATEGORY_CREATE",
                entity_type="category",
                entity_id=uuid4(),
                payload={
                    "expected_version": 1,
                    "command_payload": {
                        "code": f"operation-{uuid4().hex[:12]}",
                        "slug": f"operation-{uuid4().hex[:12]}",
                        "name": "Operation review fixture",
                    },
                },
                status="WAITING_APPROVAL",
                version=1,
                idempotency_key=str(uuid4()),
                request_hash=hashlib.sha256(b"operation review").hexdigest(),
                requested_by=requester.id,
                reason_code="TAXONOMY_CHANGE",
            )
            session.add(operation)
            await session.commit()
            actor = SimpleNamespace(
                id=approver.id,
                permissions={"operations.approve", "taxonomy.category.publish"},
                permission_scopes={},
                step_up_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            )
            approval_key = uuid4()
            request = _request(
                f"/admin/v1/operations/{operation.id}/approve",
                method="POST",
            )
            request.state.request_id = "operation-review-request"
            approved = await iam.approve_operation(
                operation_id=operation.id,
                data=ReasonAction(reason_code="TAXONOMY_CHANGE"),
                request=request,
                idempotency_key=approval_key,
                if_match='"1"',
                current=actor,
                db=session,
            )
            assert approved.status == "QUEUED"
            assert approved.version == 2
            await session.refresh(operation)
            assert operation.approved_by == approver.id
            assert operation.approval_key == str(approval_key)
            replay = await iam.approve_operation(
                operation_id=operation.id,
                data=ReasonAction(reason_code="TAXONOMY_CHANGE"),
                request=request,
                idempotency_key=approval_key,
                if_match='"1"',
                current=actor,
                db=session,
            )
            assert replay.operation_id == approved.operation_id
            assert replay.version == approved.version
            outbox = await session.scalar(
                select(ModerationOutboxEvent).where(
                    ModerationOutboxEvent.idempotency_key == f"taxonomy-command:{operation.id}"
                )
            )
            assert outbox is not None
            assert outbox.payload["command"]["approved_by_staff_id"] == str(approver.id)
    finally:
        await engine.dispose()
