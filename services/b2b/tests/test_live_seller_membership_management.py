import asyncio
import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from src.api.deps import _seller_from_token, get_current_seller
from src.core.identity import SellerPrincipal
from src.core.security import create_access_token
from src.core.database import get_db
from src.main import app
from src.models.seller import Seller
from src.models.seller_membership import SellerMembership
from src.models.seller_membership_audit import SellerMembershipAudit
from src.models.seller_user import SellerUser
from fastapi import HTTPException


@pytest.mark.postgres_integration
def test_live_team_role_change_and_revocation_are_audited_and_revoke_sessions() -> None:
    database_url = os.getenv("NEOMARKET_POSTGRES_TEST_URL")
    if not database_url:
        pytest.skip("set NEOMARKET_POSTGRES_TEST_URL to run PostgreSQL integration tests")

    async def scenario() -> None:
        engine = create_async_engine(database_url, poolclass=NullPool)
        sessions = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        seller_id, owner_id, member_id = uuid4(), uuid4(), uuid4()
        seller = Seller(
            id=seller_id,
            email=f"owner-{uuid4()}@example.com",
            hashed_password="test-only-hash",
            company_name="Membership lifecycle integration test",
            is_active=True,
            account_status="ACTIVE",
        )
        owner = SellerUser(
            id=owner_id,
            email=f"owner-{uuid4()}@example.com",
            hashed_password="test-only-hash",
            is_active=True,
        )
        member = SellerUser(
            id=member_id,
            email=f"member-{uuid4()}@example.com",
            hashed_password="test-only-hash",
            is_active=True,
        )
        owner_membership = SellerMembership(
            seller_id=seller_id, user_id=owner_id, role="OWNER", active=True
        )
        member_membership = SellerMembership(
            seller_id=seller_id, user_id=member_id, role="VIEWER", active=True
        )

        async with sessions() as session:
            session.add_all([seller, owner, member])
            await session.flush()
            session.add_all([owner_membership, member_membership])
            await session.commit()

        original_overrides = app.dependency_overrides.copy()

        async def override_get_db():
            async with sessions() as session:
                yield session

        async def override_current_seller():
            return SellerPrincipal(seller, owner, owner_membership)

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_seller] = override_current_seller
        client = TestClient(app)
        stale_member_token = create_access_token(
            str(member_id), member.session_version, seller_id=str(seller_id)
        )
        try:
            changed = client.patch(
                f"/team/members/{member_id}",
                headers={"If-Match": '"1"'},
                json={"role": "FINANCE", "reason": "Finance duties assigned"},
            )
            assert changed.status_code == 200, changed.text
            assert changed.headers["ETag"] == '"2"'
            assert changed.json()["role"] == "FINANCE"
            assert changed.json()["revision"] == 2

            async with sessions() as session:
                with pytest.raises(HTTPException) as revoked_session:
                    await _seller_from_token(stale_member_token, session)
                assert revoked_session.value.status_code == 401

            stale = client.patch(
                f"/team/members/{member_id}",
                headers={"If-Match": '"1"'},
                json={"role": "VIEWER", "reason": "Stale role update"},
            )
            assert stale.status_code == 412, stale.text

            owner_role_assignment = client.patch(
                f"/team/members/{member_id}",
                headers={"If-Match": '"2"'},
                json={"role": "OWNER", "reason": "Attempt owner escalation"},
            )
            assert owner_role_assignment.status_code in {400, 422}

            revoked = client.request(
                "DELETE",
                f"/team/members/{member_id}",
                headers={"If-Match": '"2"'},
                json={"reason": "Access no longer required"},
            )
            assert revoked.status_code == 204, revoked.text

            async with sessions() as session:
                membership = await session.scalar(
                    select(SellerMembership).where(
                        SellerMembership.seller_id == seller_id,
                        SellerMembership.user_id == member_id,
                    )
                )
                persisted_user = await session.get(SellerUser, member_id)
                audits = list(
                    (
                        await session.scalars(
                            select(SellerMembershipAudit)
                            .where(SellerMembershipAudit.target_user_id == member_id)
                            .order_by(SellerMembershipAudit.occurred_at)
                        )
                    ).all()
                )
                assert membership is not None
                assert membership.active is False and membership.revision == 3
                assert persisted_user is not None and persisted_user.session_version == 2
                assert [audit.action for audit in audits] == [
                    "ROLE_CHANGED",
                    "MEMBERSHIP_REVOKED",
                ]
                assert [audit.previous_role for audit in audits] == ["VIEWER", "FINANCE"]
                assert [audit.new_role for audit in audits] == ["FINANCE", None]
                assert [audit.reason for audit in audits] == [
                    "Finance duties assigned",
                    "Access no longer required",
                ]
                assert all(audit.actor_user_id == owner_id for audit in audits)

                with pytest.raises(DBAPIError):
                    await session.execute(
                        update(SellerMembershipAudit)
                        .where(SellerMembershipAudit.target_user_id == member_id)
                        .values(reason="attempted mutation")
                    )
                await session.rollback()
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides.update(original_overrides)
            async with sessions() as session:
                await session.execute(
                    SellerMembership.__table__.delete().where(
                        SellerMembership.seller_id == seller_id
                    )
                )
                await session.execute(
                    SellerUser.__table__.delete().where(SellerUser.id.in_([owner_id, member_id]))
                )
                await session.execute(Seller.__table__.delete().where(Seller.id == seller_id))
                await session.commit()
            await engine.dispose()

    asyncio.run(scenario())
