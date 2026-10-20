import base64
import hashlib
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
import jwt

from src.core import security
from src.core.config import settings
from src.api import deps
from src.services.auth_service import AuthService
from src.models.seller import Seller
from src.models.seller_session import SellerSession
from src.models.seller_membership import SellerMembership
from src.models.seller_user import SellerUser


def test_login_token_response_uses_configured_expiry(monkeypatch):
    monkeypatch.setattr(settings, "access_token_expire_minutes", 7)
    seller = SimpleNamespace(id=uuid4(), session_version=0)

    response = AuthService(object()).create_token(seller)
    payload = security.decode_access_token_payload(response.access_token)

    assert response.expires_in == 420
    assert payload is not None
    assert payload["exp"] - payload["iat"] == 420


def test_b2b_rejects_wrong_issuer_or_audience():
    token = jwt.encode(
        {
            "sub": str(uuid4()),
            "iss": "attacker",
            "aud": "wrong-api",
        },
        settings.secret_key,
        algorithm=settings.algorithm,
    )
    assert security.decode_access_token(token) is None


def test_b2b_rejects_expired_and_not_yet_valid_tokens():
    now = datetime.now(timezone.utc)
    for claims in (
        {"exp": now - timedelta(minutes=1), "iat": now - timedelta(minutes=2), "nbf": now - timedelta(minutes=2)},
        {"exp": now + timedelta(minutes=5), "iat": now, "nbf": now + timedelta(minutes=1)},
    ):
        token = jwt.encode(
            {"sub": str(uuid4()), "iss": settings.jwt_issuer, "aud": settings.jwt_audience, **claims},
            settings.secret_key,
            algorithm=settings.algorithm,
        )
        assert security.decode_access_token(token) is None


def test_b2b_rejects_unsigned_token():
    header = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').rstrip(b"=")
    payload = base64.urlsafe_b64encode(json.dumps({"sub": str(uuid4())}).encode()).rstrip(b"=")
    token = b".".join((header, payload, b"")).decode()
    assert security.decode_access_token(token) is None


def test_b2b_rejects_token_with_unknown_key_id():
    token = jwt.encode(
        {"sub": str(uuid4()), "iss": settings.jwt_issuer, "aud": settings.jwt_audience},
        settings.secret_key,
        algorithm=settings.algorithm,
        headers={"kid": "retired-key"},
    )
    assert security.decode_access_token(token) is None


def test_b2b_rejects_token_missing_required_exp_claim():
    token = jwt.encode(
        {"sub": str(uuid4()), "iss": settings.jwt_issuer, "aud": settings.jwt_audience,
         "iat": datetime.now(timezone.utc), "nbf": datetime.now(timezone.utc)},
        settings.secret_key,
        algorithm=settings.algorithm,
        headers={"kid": settings.jwt_kid},
    )
    assert security.decode_access_token(token) is None


@pytest.mark.asyncio
async def test_b2b_rejects_revoked_and_unversioned_seller_tokens(monkeypatch):
    seller_id = uuid4()
    seller = SimpleNamespace(
        id=seller_id,
        is_active=True,
        account_status="ACTIVE",
        session_version=1,
    )

    class FakeSellerRepository:
        def __init__(self, _session):
            pass

        async def get_by_id(self, _seller_id):
            return seller

    monkeypatch.setattr(deps, "SellerRepository", FakeSellerRepository)
    stale_token = security.create_access_token(str(seller_id), session_version=0)
    with pytest.raises(HTTPException) as exc_info:
        await deps._seller_from_token(stale_token, object())
    assert exc_info.value.status_code == 401

    current_token = security.create_access_token(str(seller_id), session_version=1)
    assert await deps._seller_from_token(current_token, object()) is seller

    now = datetime.now(timezone.utc)
    legacy_token = jwt.encode(
        {
            "sub": str(seller_id),
            "iat": now,
            "nbf": now,
            "exp": now + timedelta(minutes=5),
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
        },
        settings.secret_key,
        algorithm=settings.algorithm,
        headers={"kid": settings.jwt_kid},
    )
    with pytest.raises(HTTPException) as exc_info:
        await deps._seller_from_token(legacy_token, object())
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_b2b_resolves_staff_token_to_active_membership(monkeypatch):
    from datetime import datetime, timezone

    from src.models.seller import Seller
    from src.models.seller_membership import SellerMembership
    from src.models.seller_user import SellerUser

    seller_id, user_id = uuid4(), uuid4()
    seller = Seller(
        id=seller_id,
        email="owner@example.test",
        hashed_password="unused",
        company_name="Seller organization",
        is_active=True,
        account_status="ACTIVE",
    )
    user = SellerUser(
        id=user_id,
        email="staff@example.test",
        hashed_password="unused",
        is_active=True,
        email_verified_at=datetime.now(timezone.utc),
        session_version=4,
    )
    membership = SellerMembership(
        seller_id=seller_id, user_id=user_id, role="CATALOG_EDITOR", active=True
    )

    class FakeSellerRepository:
        def __init__(self, _session):
            pass

        async def get_by_id(self, requested_seller_id):
            assert requested_seller_id == seller_id
            return seller

        async def get_user_by_id(self, requested_user_id):
            assert requested_user_id == user_id
            return user

        async def get_membership(self, requested_seller_id, requested_user_id):
            assert requested_seller_id == seller_id
            assert requested_user_id == user_id
            return membership

    monkeypatch.setattr(deps, "SellerRepository", FakeSellerRepository)
    token = security.create_access_token(
        str(user_id), session_version=4, seller_id=str(seller_id)
    )

    principal = await deps._seller_from_token(token, object())

    assert principal.id == seller_id
    assert principal.user_id == user_id
    assert principal.role == "CATALOG_EDITOR"


@pytest.mark.asyncio
async def test_b2b_resolves_active_opaque_session_and_rejects_revoked_session(monkeypatch):
    from datetime import datetime, timedelta, timezone

    seller_id, user_id = uuid4(), uuid4()
    seller = Seller(
        id=seller_id,
        email="owner@example.test",
        hashed_password="unused",
        company_name="Opaque organization",
        is_active=True,
        account_status="ACTIVE",
        session_version=3,
    )
    user = SellerUser(
        id=user_id,
        email="owner@example.test",
        hashed_password="unused",
        is_active=True,
        email_verified_at=datetime.now(timezone.utc),
        session_version=7,
    )
    membership = SellerMembership(
        seller_id=seller_id, user_id=user_id, role="OWNER", active=True
    )
    raw = "opaque-session-token"
    session = SellerSession(
        id=uuid4(),
        token_hash=hashlib.sha256(raw.encode()).hexdigest(),
        seller_id=seller_id,
        user_id=user_id,
        user_session_version=7,
        seller_session_version=3,
        refresh_family_id=uuid4(),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        refresh_expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        last_seen_at=datetime.now(timezone.utc),
    )

    class FakeDB:
        async def scalar(self, _statement):
            return session

    class FakeSellerRepository:
        def __init__(self, _session):
            pass

        async def get_by_id(self, requested_seller_id):
            assert requested_seller_id == seller_id
            return seller

        async def get_user_by_id(self, requested_user_id):
            assert requested_user_id == user_id
            return user

        async def get_membership(self, requested_seller_id, requested_user_id):
            assert requested_seller_id == seller_id
            assert requested_user_id == user_id
            return membership

    monkeypatch.setattr(deps, "SellerRepository", FakeSellerRepository)
    principal = await deps._seller_from_token(raw, FakeDB())
    assert principal.id == seller_id
    assert principal.user_id == user_id

    session.revoked_at = datetime.now(timezone.utc)
    with pytest.raises(HTTPException) as error:
        await deps._seller_from_token(raw, FakeDB())
    assert error.value.status_code == 401


@pytest.mark.asyncio
async def test_refresh_window_can_resolve_expired_access_session(monkeypatch):
    from datetime import datetime, timedelta, timezone

    seller_id, user_id = uuid4(), uuid4()
    seller = SimpleNamespace(id=seller_id, is_active=True, account_status="ACTIVE", session_version=1)
    user = SimpleNamespace(id=user_id, is_active=True, email_verified_at=datetime.now(timezone.utc), session_version=2)
    membership = SimpleNamespace(seller_id=seller_id, user_id=user_id, active=True, role="OWNER")
    raw = "expired-access-with-refresh-window"
    session = SimpleNamespace(
        token_hash=hashlib.sha256(raw.encode()).hexdigest(),
        seller_id=seller_id,
        user_id=user_id,
        revoked_at=None,
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        refresh_expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        user_session_version=2,
        seller_session_version=1,
    )

    class FakeDB:
        async def scalar(self, _statement):
            return session

    class FakeSellerRepository:
        def __init__(self, _session):
            pass

        async def get_by_id(self, _seller_id):
            return seller

        async def get_user_by_id(self, _user_id):
            return user

        async def get_membership(self, _seller_id, _user_id):
            return membership

    monkeypatch.setattr(deps, "SellerRepository", FakeSellerRepository)
    with pytest.raises(HTTPException):
        await deps._seller_from_token(raw, FakeDB())
    principal = await deps._seller_from_opaque_session(raw, FakeDB(), allow_expired=True)
    assert principal.id == seller_id
