from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from src.core.security import hash_password
from src.models.seller import Seller
from src.models.seller_user import SellerUser
from src.services.auth_service import AuthService


@pytest.mark.asyncio
async def test_inactive_seller_cannot_authenticate() -> None:
    seller = Seller(
        email="inactive@example.invalid",
        hashed_password=hash_password("correct-test-password"),
        company_name="Inactive test seller",
        is_active=False,
        account_status="SUSPENDED",
        email_verified_at=datetime.now(timezone.utc),
    )
    service = AuthService(None)  # repository session is unused by this focused test
    service.repo.get_user_by_email = AsyncMock(
        return_value=SellerUser(
            id=seller.id,
            email=seller.email,
            hashed_password=seller.hashed_password,
            is_active=False,
            email_verified_at=seller.email_verified_at,
        )
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.authenticate("inactive@example.invalid", "correct-test-password")

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Account is inactive"


@pytest.mark.asyncio
async def test_member_authentication_returns_database_scoped_role_context() -> None:
    from uuid import uuid4

    from src.models.seller_membership import SellerMembership

    seller = Seller(
        id=uuid4(),
        email="owner@example.invalid",
        hashed_password=hash_password("correct-test-password"),
        company_name="Active tenant",
        is_active=True,
        account_status="ACTIVE",
        email_verified_at=datetime.now(timezone.utc),
    )
    user = SellerUser(
        id=uuid4(),
        email="staff@example.invalid",
        hashed_password=hash_password("correct-test-password"),
        is_active=True,
        email_verified_at=datetime.now(timezone.utc),
    )
    membership = SellerMembership(
        seller_id=seller.id, user_id=user.id, role="VIEWER", active=True
    )
    service = AuthService(None)
    service.repo.get_by_email = AsyncMock(return_value=None)
    service.repo.get_user_by_email = AsyncMock(return_value=user)
    service.repo.list_active_memberships = AsyncMock(return_value=[membership])
    service.repo.get_by_id = AsyncMock(return_value=seller)

    principal = await service.authenticate(user.email, "correct-test-password")

    assert principal.id == seller.id
    assert principal.user_id == user.id
    assert principal.role == "VIEWER"
