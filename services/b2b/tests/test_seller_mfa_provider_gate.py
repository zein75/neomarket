from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.routers import auth as auth_router
from src.core.identity import SellerPrincipal
from src.main import app
from src.models.seller import Seller
from src.models.seller_membership import SellerMembership
from src.models.seller_user import SellerUser


@pytest.mark.parametrize("path", ["/auth/mfa/challenge", "/auth/mfa/verify"])
def test_seller_mfa_fails_closed_until_provider_is_configured(path: str) -> None:
    seller_id, user_id = uuid4(), uuid4()
    principal = SellerPrincipal(
        Seller(
            id=seller_id,
            email="owner@example.test",
            hashed_password="unused",
            company_name="MFA gate organization",
            is_active=True,
            account_status="ACTIVE",
        ),
        SellerUser(id=user_id, email="owner@example.test", hashed_password="unused", is_active=True),
        SellerMembership(seller_id=seller_id, user_id=user_id, role="OWNER", active=True),
    )

    async def authenticated_owner():
        return principal

    app.dependency_overrides[auth_router.get_current_seller] = authenticated_owner
    try:
        response = TestClient(app).post(path)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 501
    assert response.json() == {
        "code": "FEATURE_NOT_CONFIGURED",
        "message": "Seller MFA provider is not configured",
    }
