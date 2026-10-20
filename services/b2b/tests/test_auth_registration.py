from unittest.mock import AsyncMock
from uuid import uuid4
import hashlib

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from src.models.seller import Seller
from src.schemas.seller import SellerCreate
from src.services.auth_service import AuthService


@pytest.mark.asyncio
async def test_register_normalizes_email_before_lookup_and_insert() -> None:
    seller = Seller(id=uuid4(), email="seller@example.com", hashed_password="hash", company_name="Seller")
    service = AuthService(None)
    service.repo.get_by_email = AsyncMock(return_value=None)
    service.repo.create = AsyncMock(return_value=seller)
    service.repo.create_user = AsyncMock()
    service.repo.create_membership = AsyncMock()
    service.repo.create_email_verification = AsyncMock()

    registered, token = await service.register(
        SellerCreate(email="Seller@Example.com", password="long-test-password", company_name="Seller")
    )

    assert registered is seller
    assert len(token) >= 32
    service.repo.get_by_email.assert_awaited_once_with("seller@example.com")
    assert service.repo.create.await_args.kwargs["email"] == "seller@example.com"
    assert service.repo.create.await_args.kwargs["is_active"] is False
    assert service.repo.create.await_args.kwargs["account_status"] == "PENDING_EMAIL"
    service.repo.create_user.assert_awaited_once()
    assert service.repo.create_user.await_args.kwargs["user_id"] == seller.id
    assert service.repo.create_user.await_args.kwargs["email"] == "seller@example.com"
    assert service.repo.create_membership.await_args.kwargs["role"] == "OWNER"
    challenge_args = service.repo.create_email_verification.await_args.args
    assert challenge_args[0] == seller.id
    assert challenge_args[1] != token


@pytest.mark.asyncio
async def test_register_rejects_existing_case_insensitive_email() -> None:
    existing = Seller(id=uuid4(), email="seller@example.com", hashed_password="hash", company_name="Seller")
    service = AuthService(None)
    service.repo.get_by_email = AsyncMock(return_value=existing)
    service.repo.create = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await service.register(
            SellerCreate(email="SELLER@example.com", password="long-test-password", company_name="Duplicate")
        )

    assert exc_info.value.status_code == 409
    service.repo.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_register_maps_database_unique_race_to_conflict_and_rolls_back() -> None:
    service = AuthService(None)
    service.repo.get_by_email = AsyncMock(return_value=None)
    service.repo.create = AsyncMock(side_effect=IntegrityError("insert", {}, RuntimeError("unique")))
    service.repo.session = type("Session", (), {"rollback": AsyncMock()})()

    with pytest.raises(HTTPException) as exc_info:
        await service.register(
            SellerCreate(email="seller@example.com", password="long-test-password", company_name="Seller")
        )

    assert exc_info.value.status_code == 409
    service.repo.session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_verify_email_consumes_token_and_only_moves_to_pending_review() -> None:
    from datetime import datetime, timedelta, timezone

    import hashlib
    from src.models.seller_email_verification import SellerEmailVerification

    token = "test-verification-token-long-enough-123456"
    seller = Seller(
        id=uuid4(),
        email="seller@example.com",
        hashed_password="hash",
        company_name="Seller",
        is_active=False,
        account_status="PENDING_EMAIL",
    )
    challenge = SellerEmailVerification(
        id=uuid4(),
        seller_id=seller.id,
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    service = AuthService(None)
    service.repo.get_email_verification_by_hash = AsyncMock(return_value=challenge)
    service.repo.get_by_id = AsyncMock(return_value=seller)
    from src.models.seller_user import SellerUser

    user = SellerUser(
        id=seller.id,
        email=seller.email,
        hashed_password=seller.hashed_password,
        email_verified_at=None,
    )
    service.repo.get_user_by_id = AsyncMock(return_value=user)
    service.repo.session = type("Session", (), {"flush": AsyncMock()})()

    async def consume(challenge_id, now):
        assert challenge_id == challenge.id
        challenge.consumed_at = now
        return True

    service.repo.consume_email_verification = AsyncMock(side_effect=consume)

    status = await service.verify_email(token)

    assert status == "PENDING_REVIEW"
    assert seller.email_verified_at is not None
    assert seller.is_active is False
    assert user.email_verified_at is not None
    assert challenge.consumed_at is not None


@pytest.mark.asyncio
async def test_create_opaque_session_stores_only_token_digest_and_expiry() -> None:
    class Session:
        def __init__(self):
            self.rows = []

        def add(self, row):
            self.rows.append(row)

        async def flush(self):
            return None

    seller = Seller(
        id=uuid4(),
        email="seller@example.com",
        hashed_password="hash",
        company_name="Seller",
        session_version=4,
    )
    session = Session()
    service = AuthService(None)
    service.repo.session = session

    result = await service.create_opaque_session(
        seller,
        device_label="Seller browser",
        user_agent="Playwright",
        ip_address="127.0.0.1",
    )

    assert result.token_type == "bearer"
    assert result.expires_in <= 900
    assert len(result.access_token) >= 40
    assert len(session.rows) == 1
    stored = session.rows[0]
    assert stored.token_hash == hashlib.sha256(result.access_token.encode()).hexdigest()
    assert stored.token_hash != result.access_token
    assert stored.seller_session_version == 4
    assert stored.device_label == "Seller browser"
