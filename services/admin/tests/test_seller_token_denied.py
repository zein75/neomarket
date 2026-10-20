"""A valid B2B seller JWT must not authenticate an Admin API request."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.api import deps
from src.api.routers import moderation


B2B_TEST_SIGNING_KEY = "b2b-local-test-signing-key-not-for-deployment"


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, value: object) -> None:
        self.added.append(value)

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


@pytest.mark.asyncio
async def test_valid_b2b_seller_access_token_is_denied_by_admin_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.core.config import settings

    seller_id = str(uuid4())
    now = datetime.now(timezone.utc)
    seller_token = jwt.encode(
        {
            "sub": seller_id,
            "seller_id": seller_id,
            "session_version": 4,
            "iat": now,
            "nbf": now,
            "exp": now + timedelta(minutes=10),
            "iss": "neomarket-b2b",
            "aud": "neomarket-b2b-api",
        },
        B2B_TEST_SIGNING_KEY,
        algorithm="HS256",
        headers={"kid": "managed-v1"},
    )
    # Confirm this is a valid token in the format accepted by B2B, not a
    # malformed bearer string that would make the Admin assertion vacuous.
    seller_claims = jwt.decode(
        seller_token,
        B2B_TEST_SIGNING_KEY,
        algorithms=["HS256"],
        issuer="neomarket-b2b",
        audience="neomarket-b2b-api",
    )
    assert seller_claims["seller_id"] == seller_id

    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "admin_allow_dev_auth", False)

    database = FakeSession()
    app = FastAPI()
    app.include_router(moderation.router)

    async def database_session() -> FakeSession:
        return database

    app.dependency_overrides[deps.get_db] = database_session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://admin.test"
    ) as client:
        response = await client.get(
            "/admin/v1/moderation/tickets",
            headers={"Authorization": f"Bearer {seller_token}"},
        )

    assert response.status_code == 401
    assert response.json()["detail"] == "Opaque Admin session cookie required"
    assert seller_token not in response.text
    assert len(database.added) == 1
    audit = database.added[0]
    assert audit.action == "ADMIN_AUTH_FAILED"
    assert audit.details == {
        "auth_kind": "staff",
        "method": "GET",
        "path": "/admin/v1/moderation/tickets",
        "status_code": 401,
    }
