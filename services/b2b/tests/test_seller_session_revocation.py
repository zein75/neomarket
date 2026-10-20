import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from src.api.deps import _seller_from_token
from src.api.routers.auth import logout_all
from src.core.security import create_access_token, hash_password
from src.models.seller import Seller
from src.models.seller_membership import SellerMembership
from src.models.seller_user import SellerUser
from src.repositories.seller_repo import SellerRepository
from src.services.auth_service import AuthService


@pytest.mark.asyncio
async def test_postgres_logout_all_revokes_previously_issued_tokens() -> None:
    database_url = os.getenv("NEOMARKET_POSTGRES_TEST_URL")
    if not database_url:
        pytest.skip("set NEOMARKET_POSTGRES_TEST_URL to run PostgreSQL integration tests")

    engine = create_async_engine(database_url)
    seller = Seller(
        id=uuid4(),
        email=f"{uuid4()}@session-test.invalid",
        hashed_password="test-only-hash",
        company_name="Session revocation test",
    )
    old_token = ""

    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            session.add(seller)
            await session.commit()
            old_token = create_access_token(str(seller.id), seller.session_version)

            assert await logout_all(seller, session) == {"ok": True}
            await session.refresh(seller)
            assert seller.session_version == 1

        # A protected API request creates a fresh session and must observe the committed version.
        async with AsyncSession(engine, expire_on_commit=False) as request_session:
            with pytest.raises(HTTPException) as exc_info:
                await _seller_from_token(old_token, request_session)
            assert exc_info.value.status_code == 401

            refreshed_seller = await request_session.get(Seller, seller.id)
            assert refreshed_seller is not None
            fresh_token = create_access_token(str(seller.id), refreshed_seller.session_version)
            assert await _seller_from_token(fresh_token, request_session) is refreshed_seller
    finally:
        async with AsyncSession(engine) as cleanup_session:
            persisted_seller = await cleanup_session.get(Seller, seller.id)
            if persisted_seller is not None:
                await cleanup_session.delete(persisted_seller)
                await cleanup_session.commit()
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_suspension_disables_seller_and_revokes_existing_session() -> None:
    database_url = os.getenv("NEOMARKET_POSTGRES_TEST_URL")
    if not database_url:
        pytest.skip("set NEOMARKET_POSTGRES_TEST_URL to run PostgreSQL integration tests")

    engine = create_async_engine(database_url)
    password = "DisposableSeller!2026"
    seller = Seller(
        id=uuid4(),
        email=f"{uuid4()}@suspension-test.invalid",
        hashed_password=hash_password(password),
        company_name="Suspension integration test",
        is_active=True,
        account_status="ACTIVE",
        email_verified_at=datetime.now(timezone.utc),
    )
    user = SellerUser(
        id=uuid4(),
        email=seller.email,
        hashed_password=hash_password(password),
        is_active=True,
        email_verified_at=seller.email_verified_at,
    )
    old_token = ""

    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            session.add_all([seller, user])
            await session.commit()
            session.add(SellerMembership(seller_id=seller.id, user_id=user.id, role="OWNER", active=True))
            await session.commit()
            old_token = create_access_token(str(seller.id), seller.session_version)

            assert await SellerRepository(session).suspend(seller.id)
            await session.commit()
            await session.refresh(seller)
            assert seller.account_status == "SUSPENDED"
            assert seller.is_active is False
            assert seller.session_version == 1

        async with AsyncSession(engine, expire_on_commit=False) as request_session:
            with pytest.raises(HTTPException) as exc_info:
                await _seller_from_token(old_token, request_session)
            assert exc_info.value.status_code == 401

            with pytest.raises(HTTPException) as login_error:
                await AuthService(request_session).authenticate(seller.email, password)
            assert login_error.value.status_code == 403
    finally:
        async with AsyncSession(engine) as cleanup_session:
            persisted_seller = await cleanup_session.get(Seller, seller.id)
            if persisted_seller is not None:
                await cleanup_session.delete(persisted_seller)
            persisted_user = await cleanup_session.get(SellerUser, user.id)
            if persisted_user is not None:
                await cleanup_session.delete(persisted_user)
            await cleanup_session.commit()
        await engine.dispose()
