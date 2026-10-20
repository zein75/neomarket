from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.routers import products as products_router
from src.api.routers import auth as auth_router
from src.core.identity import SellerPrincipal
from src.main import app
from src.models.seller import Seller
from src.models.seller_membership import SellerMembership
from src.models.seller_user import SellerUser


@pytest.mark.parametrize("role", ["VIEWER", "FINANCE", "WAREHOUSE_OPERATOR", "SUPPORT"])
def test_read_only_or_scoped_member_cannot_edit_product(role: str) -> None:
    seller_id, user_id = uuid4(), uuid4()
    organization = Seller(
        id=seller_id,
        email="owner@example.test",
        hashed_password="unused",
        company_name="Role test organization",
        is_active=True,
        account_status="ACTIVE",
    )
    user = SellerUser(
        id=user_id,
        email="member@example.test",
        hashed_password="unused",
        is_active=True,
    )
    membership = SellerMembership(
        seller_id=seller_id, user_id=user_id, role=role, active=True
    )
    principal = SellerPrincipal(organization, user, membership)

    async def authenticated_member():
        return principal

    async def fake_db():
        yield object()

    app.dependency_overrides[products_router.get_current_seller] = authenticated_member
    app.dependency_overrides[products_router.get_db] = fake_db
    try:
        response = TestClient(app).put(
            f"/api/v1/seller/products/{uuid4()}",
            headers={"If-Match": '"1"'},
            json={"title": "Unauthorized product edit"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403
    assert response.json()["code"] == "SELLER_PERMISSION_DENIED"


@pytest.mark.parametrize(
    ("role", "can_fulfill"),
    [("OWNER", True), ("WAREHOUSE_OPERATOR", True), ("SUPPORT", False), ("VIEWER", False)],
)
def test_permissions_endpoint_returns_server_resolved_order_capability(
    role: str, can_fulfill: bool
) -> None:
    seller_id, user_id = uuid4(), uuid4()
    organization = Seller(
        id=seller_id,
        email="owner@example.test",
        hashed_password="unused",
        company_name="Role test organization",
        is_active=True,
        account_status="ACTIVE",
    )
    principal = SellerPrincipal(
        organization,
        SellerUser(id=user_id, email="member@example.test", hashed_password="unused", is_active=True),
        SellerMembership(seller_id=seller_id, user_id=user_id, role=role, active=True),
    )

    async def authenticated_member():
        return principal

    app.dependency_overrides[auth_router.get_current_seller] = authenticated_member
    try:
        response = TestClient(app).get("/auth/permissions")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["role"] == role
    assert "orders.read" in body["permissions"]
    assert ("orders.fulfill" in body["permissions"]) is can_fulfill
