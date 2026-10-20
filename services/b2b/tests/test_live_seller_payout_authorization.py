import asyncio
import os
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.core.security import hash_password
from src.models.seller import Seller
from src.models.seller_membership import SellerMembership
from src.models.seller_user import SellerUser


@pytest.mark.postgres_integration
def test_live_warehouse_operator_cannot_start_payout() -> None:
    database_url = os.getenv("NEOMARKET_POSTGRES_TEST_URL")
    b2b_url = os.getenv("NEOMARKET_B2B_TEST_URL")
    if not database_url or not b2b_url:
        pytest.skip("set PostgreSQL and B2B URLs for payout authorization integration")

    async def scenario() -> None:
        engine = create_async_engine(database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        seller_id, owner_id, operator_id = uuid4(), uuid4(), uuid4()
        password = "DisposablePayoutRole!2026"
        emails = [f"payout-role-{uuid4()}@example.com" for _ in range(2)]
        try:
            async with sessions() as session:
                password_hash = hash_password(password)
                now = datetime.now(timezone.utc)
                session.add_all(
                    [
                        Seller(
                            id=seller_id,
                            email=emails[0],
                            hashed_password=password_hash,
                            company_name="Disposable payout role seller",
                            is_active=True,
                            account_status="ACTIVE",
                            email_verified_at=now,
                        ),
                        SellerUser(id=owner_id, email=emails[0], hashed_password=password_hash, is_active=True, email_verified_at=now),
                        SellerUser(id=operator_id, email=emails[1], hashed_password=password_hash, is_active=True, email_verified_at=now),
                    ]
                )
                await session.commit()
                session.add_all(
                    [
                        SellerMembership(seller_id=seller_id, user_id=owner_id, role="OWNER", active=True),
                        SellerMembership(seller_id=seller_id, user_id=operator_id, role="WAREHOUSE_OPERATOR", active=True),
                    ]
                )
                await session.commit()

            with httpx.Client(timeout=20) as client:
                tokens = []
                for email in emails:
                    login = client.post(
                        f"{b2b_url}/auth/login",
                        data={"username": email, "password": password},
                    )
                    assert login.status_code == 200, login.text
                    tokens.append(login.json()["access_token"])
                path = f"{b2b_url}/api/v1/seller/finance/payouts"
                operator = client.post(path, headers={"Authorization": f"Bearer {tokens[1]}"})
                assert operator.status_code == 403, operator.text
                owner = client.post(path, headers={"Authorization": f"Bearer {tokens[0]}"})
                assert owner.status_code == 501, owner.text
                assert owner.json()["code"] == "FEATURE_NOT_CONFIGURED"
        finally:
            async with sessions() as session:
                await session.execute(delete(SellerMembership).where(SellerMembership.seller_id == seller_id))
                await session.execute(delete(SellerUser).where(SellerUser.id.in_([owner_id, operator_id])))
                await session.execute(delete(Seller).where(Seller.id == seller_id))
                await session.commit()
            await engine.dispose()

    asyncio.run(scenario())
