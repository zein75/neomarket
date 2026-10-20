from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.deps import get_current_seller
from src.core.identity import SellerPrincipal
from src.main import app
from src.models.seller import Seller
from src.models.seller_membership import SellerMembership
from src.models.seller_user import SellerUser


def _restore_overrides(original: dict) -> None:
    app.dependency_overrides.clear()
    app.dependency_overrides.update(original)


def test_finance_routes_return_explicit_not_configured_without_fake_amounts() -> None:
    seller_id, user_id = uuid4(), uuid4()
    principal = SellerPrincipal(
        Seller(
            id=seller_id,
            email="finance-owner@example.com",
            hashed_password="unused-test-hash",
            company_name="Finance gate fixture",
            is_active=True,
            account_status="ACTIVE",
        ),
        SellerUser(
            id=user_id,
            email="finance-owner@example.com",
            hashed_password="unused-test-hash",
            is_active=True,
        ),
        SellerMembership(seller_id=seller_id, user_id=user_id, role="OWNER", active=True),
    )
    original = app.dependency_overrides.copy()

    async def authenticated_owner():
        return principal

    app.dependency_overrides[get_current_seller] = authenticated_owner
    try:
        client = TestClient(app)
        paths = [
            "/api/v1/seller/finance/overview?period=30d",
            "/api/v1/seller/finance/transactions",
            "/api/v1/seller/finance/settlements",
            "/api/v1/seller/finance/payouts",
            f"/api/v1/seller/finance/statements/{uuid4()}",
        ]
        for path in paths:
            response = client.get(path)
            assert response.status_code == 501, (path, response.text)
            assert response.json()["code"] == "FEATURE_NOT_CONFIGURED"
            assert response.headers["Cache-Control"] == "no-store"
            assert not any(key in response.json() for key in ("amount", "available", "pending", "payable"))

        payout = client.post("/api/v1/seller/finance/payouts", json={})
        assert payout.status_code == 501, payout.text
        assert payout.json()["code"] == "FEATURE_NOT_CONFIGURED"
        assert payout.headers["Cache-Control"] == "no-store"
    finally:
        _restore_overrides(original)


@pytest.mark.parametrize("method", ["get", "post"])
def test_finance_routes_enforce_finance_permissions_before_feature_gate(method: str) -> None:
    seller_id, user_id = uuid4(), uuid4()
    principal = SellerPrincipal(
        Seller(
            id=seller_id,
            email="catalog-editor@example.com",
            hashed_password="unused-test-hash",
            company_name="Finance role fixture",
            is_active=True,
            account_status="ACTIVE",
        ),
        SellerUser(
            id=user_id,
            email="catalog-editor@example.com",
            hashed_password="unused-test-hash",
            is_active=True,
        ),
        SellerMembership(seller_id=seller_id, user_id=user_id, role="CATALOG_EDITOR", active=True),
    )
    original = app.dependency_overrides.copy()

    async def authenticated_viewer():
        return principal

    app.dependency_overrides[get_current_seller] = authenticated_viewer
    try:
        client = TestClient(app)
        response = (
            client.post("/api/v1/seller/finance/payouts", json={})
            if method == "post"
            else client.get("/api/v1/seller/finance/payouts")
        )
        assert response.status_code == 403, response.text
        assert response.headers["Cache-Control"] == "no-store"
    finally:
        _restore_overrides(original)
