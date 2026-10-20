import asyncio
import os
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.core.security import hash_password
from src.models.seller import Seller
from src.models.seller_membership import SellerMembership
from src.models.seller_tenant_switch_audit import SellerTenantSwitchAudit
from src.models.seller_user import SellerUser


@pytest.mark.postgres_integration
def test_live_tenant_switch_requires_membership_and_writes_audit() -> None:
    database_url = os.getenv("NEOMARKET_POSTGRES_TEST_URL")
    b2b_url = os.getenv("NEOMARKET_B2B_TEST_URL")
    if not database_url or not b2b_url:
        pytest.skip("set PostgreSQL and B2B URLs for tenant-switch integration")

    async def scenario() -> None:
        engine = create_async_engine(database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        org_a_id, org_b_id, org_c_id, user_id = uuid4(), uuid4(), uuid4(), uuid4()
        nonce = uuid4()
        emails = [f"tenant-switch-{nonce}-{i}@example.com" for i in range(4)]
        password = "DisposableTenant!2026"
        organization_ids = (org_a_id, org_b_id, org_c_id)
        audit_rows = 0
        try:
            async with sessions() as session:
                organizations = [
                    Seller(
                        id=organization_id,
                        email=emails[index],
                        hashed_password=hash_password(password),
                        company_name=f"Disposable organization {index}",
                        is_active=True,
                        account_status="ACTIVE",
                        email_verified_at=datetime.now(timezone.utc),
                    )
                    for index, organization_id in enumerate(organization_ids)
                ]
                users = [
                    SellerUser(
                        id=org.id,
                        email=org.email,
                        hashed_password=org.hashed_password,
                        is_active=True,
                        email_verified_at=org.email_verified_at,
                    )
                    for org in organizations
                ]
                staff = SellerUser(
                    id=user_id,
                    email=emails[3],
                    hashed_password=hash_password(password),
                    is_active=True,
                    email_verified_at=datetime.now(timezone.utc),
                )
                session.add_all([*organizations, *users, staff])
                await session.flush()
                session.add_all(
                    [
                        SellerMembership(seller_id=org.id, user_id=org.id, role="OWNER", active=True)
                        for org in organizations
                    ]
                    + [
                        SellerMembership(seller_id=org_a_id, user_id=user_id, role="VIEWER", active=True),
                        SellerMembership(seller_id=org_b_id, user_id=user_id, role="MANAGER", active=True),
                    ]
                )
                await session.commit()

            with httpx.Client(timeout=10) as client:
                missing_choice = client.post(
                    f"{b2b_url}/auth/login",
                    data={"username": emails[3], "password": password},
                )
                assert missing_choice.status_code == 409
                options = missing_choice.json()
                assert options["code"] == "ORGANIZATION_SELECTION_REQUIRED"
                assert {row["id"] for row in options["organizations"]} == {
                    str(org_a_id),
                    str(org_b_id),
                }

                login_a = client.post(
                    f"{b2b_url}/auth/login",
                    data={"username": emails[3], "password": password, "seller_id": str(org_a_id)},
                )
                assert login_a.status_code == 200
                token_a = login_a.json()["access_token"]
                headers_a = {"Authorization": f"Bearer {token_a}"}
                organizations_response = client.get(
                    f"{b2b_url}/auth/organizations", headers=headers_a
                )
                assert organizations_response.status_code == 200
                memberships = organizations_response.json()
                assert len(memberships) == 2
                assert next(row for row in memberships if row["current"])["id"] == str(org_a_id)

                switched = client.post(
                    f"{b2b_url}/auth/switch-tenant",
                    headers=headers_a,
                    json={"seller_id": str(org_b_id)},
                )
                assert switched.status_code == 200
                token_b = switched.json()["access_token"]
                headers_b = {"Authorization": f"Bearer {token_b}"}
                current = client.get(f"{b2b_url}/auth/me", headers=headers_b)
                assert current.status_code == 200
                assert current.json()["id"] == str(org_b_id)
                still_a = client.get(f"{b2b_url}/auth/me", headers=headers_a)
                assert still_a.status_code == 200
                assert still_a.json()["id"] == str(org_a_id)

                denied = client.post(
                    f"{b2b_url}/auth/switch-tenant",
                    headers=headers_a,
                    json={"seller_id": str(org_c_id)},
                )
                assert denied.status_code == 403
                denied_choice = client.post(
                    f"{b2b_url}/auth/login",
                    data={"username": emails[3], "password": password, "seller_id": str(org_c_id)},
                )
                assert denied_choice.status_code == 403

            async with sessions() as session:
                rows = await session.execute(
                    select(SellerTenantSwitchAudit).where(
                        SellerTenantSwitchAudit.user_id == user_id
                    )
                )
                audits = list(rows.scalars().all())
                assert len(audits) == 1
                assert audits[0].source_seller_id == org_a_id
                assert audits[0].target_seller_id == org_b_id
                assert audits[0].source_role == "VIEWER"
                assert audits[0].target_role == "MANAGER"
                audit_rows = len(audits)
        finally:
            async with sessions() as session:
                await session.execute(
                    delete(SellerTenantSwitchAudit).where(
                        SellerTenantSwitchAudit.user_id == user_id
                    )
                )
                for organization_id in organization_ids:
                    organization = await session.get(Seller, organization_id)
                    if organization is not None:
                        await session.delete(organization)
                user = await session.get(SellerUser, user_id)
                if user is not None:
                    await session.delete(user)
                await session.commit()
            async with sessions() as session:
                remaining = await session.execute(
                    select(Seller.id).where(Seller.email.in_(emails))
                )
                assert not remaining.scalars().all()
            await engine.dispose()
        assert audit_rows == 1

    asyncio.run(scenario())
