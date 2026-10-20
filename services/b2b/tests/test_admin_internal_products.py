import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.api.routers import admin_internal
from src.core.config import settings
from src.schemas.admin_internal import SafetyHoldPayload


def _test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(admin_internal.router)
    return app


def _product(product_id):
    return SimpleNamespace(
        id=product_id,
        seller_id=uuid4(),
        revision=3,
        published_revision=2,
        deleted=False,
        category_id=uuid4(),
        status="ON_MODERATION",
        created_at=datetime(2026, 10, 18, tzinfo=timezone.utc),
        skus=[
            SimpleNamespace(
                on_hand=2,
                stock=2,
                reserved_quantity=0,
                is_active=True,
            )
        ],
        updated_at=datetime(2026, 10, 18, tzinfo=timezone.utc),
    )


def test_publication_is_derived_from_public_catalog_query(monkeypatch) -> None:
    product_id = uuid4()
    product = _product(product_id)
    async def get_with_skus(_self, requested_id):
        assert requested_id == product_id
        return product

    monkeypatch.setattr(admin_internal.ProductRepository, "get_with_skus", get_with_skus)
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(settings, "service_key", "admin-internal-test-key")
    app = _test_app()
    db = SimpleNamespace()
    app.dependency_overrides[admin_internal.get_db] = lambda: db

    with TestClient(app) as client:
        response = client.get(
            f"/internal/v1/products/{product_id}/publication",
            headers={"X-Service-Key": "admin-internal-test-key"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "product_id": str(product_id),
        "current_revision": 3,
        "published_revision": 2,
        "visible": True,
        "visibility_reasons": [],
        "updated_at": "2026-10-18T00:00:00Z",
    }


def test_publication_returns_explicit_reason_when_not_in_public_catalog(
    monkeypatch,
) -> None:
    product_id = uuid4()
    product = _product(product_id)
    product.deleted = True

    async def get_with_skus(_self, requested_id):
        assert requested_id == product_id
        return product

    monkeypatch.setattr(admin_internal.ProductRepository, "get_with_skus", get_with_skus)
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(settings, "service_key", "admin-internal-test-key")
    app = _test_app()
    db = SimpleNamespace()
    app.dependency_overrides[admin_internal.get_db] = lambda: db

    with TestClient(app) as client:
        response = client.get(
            f"/internal/v1/products/{product_id}/publication",
            headers={"X-Service-Key": "admin-internal-test-key"},
        )

    assert response.status_code == 200
    assert response.json()["visible"] is False
    assert response.json()["visibility_reasons"] == ["PRODUCT_DELETED"]


def test_active_safety_hold_removes_product_from_public_catalog() -> None:
    product = _product(uuid4())
    product.safety_hold_until = datetime.now(timezone.utc) + timedelta(minutes=5)

    visible, reasons = admin_internal._product_visibility(product)

    assert visible is False
    assert reasons == ["SAFETY_HOLD"]


def test_safety_hold_expiry_requires_timezone() -> None:
    with pytest.raises(ValidationError):
        SafetyHoldPayload(reason_code="RISK_REVIEW", expires_at=datetime(2026, 10, 20))


def test_revision_returns_only_integrity_checked_snapshot_and_media_refs(
    monkeypatch,
) -> None:
    product_id = uuid4()
    seller_id = uuid4()
    content = {
        "title": "Bracket",
        "images": ["media://product/1", "media://shared"],
        "skus": [
            {"images": ["media://shared", "media://sku/1"]},
            {"images": ["media://sku/2"]},
        ],
    }
    digest = hashlib.sha256(
        json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    version = SimpleNamespace(
        product_id=product_id,
        seller_id=seller_id,
        revision=2,
        snapshot=content,
        snapshot_hash=digest,
    )

    class Result:
        def scalar_one_or_none(self):
            return version

    class Database:
        async def execute(self, _statement):
            return Result()

    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(settings, "service_key", "admin-internal-test-key")
    app = _test_app()
    app.dependency_overrides[admin_internal.get_db] = Database

    with TestClient(app) as client:
        response = client.get(
            f"/internal/v1/products/{product_id}/revisions/2",
            headers={"X-Service-Key": "admin-internal-test-key"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "product_id": str(product_id),
        "seller_id": str(seller_id),
        "revision": 2,
        "snapshot_hash": digest,
        "content": content,
        "media_refs": [
            "media://product/1",
            "media://shared",
            "media://sku/1",
            "media://sku/2",
        ],
    }


def test_revision_fails_closed_on_hash_mismatch(monkeypatch) -> None:
    product_id = uuid4()
    version = SimpleNamespace(
        product_id=product_id,
        seller_id=uuid4(),
        revision=1,
        snapshot={"title": "Tampered"},
        snapshot_hash="0" * 64,
    )

    class Result:
        def scalar_one_or_none(self):
            return version

    class Database:
        async def execute(self, _statement):
            return Result()

    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(settings, "service_key", "admin-internal-test-key")
    app = _test_app()
    app.dependency_overrides[admin_internal.get_db] = Database

    with TestClient(app) as client:
        response = client.get(
            f"/internal/v1/products/{product_id}/revisions/1",
            headers={"X-Service-Key": "admin-internal-test-key"},
        )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "PRODUCT_REVISION_INTEGRITY_FAILED"


def test_internal_product_reads_reject_anonymous_requests(monkeypatch) -> None:
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(settings, "service_key", "admin-internal-test-key")
    app = _test_app()

    with TestClient(app) as client:
        response = client.get(f"/internal/v1/products/{uuid4()}/publication")

    assert response.status_code == 401


def test_admin_product_search_uses_query_bound_keyset_cursor(monkeypatch) -> None:
    products = [_product(uuid4()), _product(uuid4())]
    created_at = datetime(2026, 10, 18, tzinfo=timezone.utc)
    for product in products:
        product.created_at = created_at

    class Scalars:
        def all(self):
            return products

    class Result:
        def scalars(self):
            return Scalars()

    class Database:
        async def execute(self, _statement):
            return Result()

    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(settings, "service_key", "admin-internal-test-key")
    app = _test_app()
    app.dependency_overrides[admin_internal.get_db] = Database

    with TestClient(app) as client:
        first = client.get(
            "/internal/v1/products?search=bracket&limit=1",
            headers={"X-Service-Key": "admin-internal-test-key"},
        )
        assert first.status_code == 200
        body = first.json()
        assert body["page"]["has_more"] is True
        assert body["items"][0]["product_id"] == str(products[0].id)

        mismatch = client.get(
            f"/internal/v1/products?search=other&cursor={body['page']['next_cursor']}",
            headers={"X-Service-Key": "admin-internal-test-key"},
        )

    assert mismatch.status_code == 422
    assert mismatch.json()["detail"]["code"] == "INVALID_CURSOR"


def test_production_rejects_unsigned_legacy_service_key(monkeypatch) -> None:
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "service_key", "a" * 48)
    monkeypatch.setattr(settings, "trusted_service_public_keys", "configured-key")

    try:
        asyncio.run(
            admin_internal.verify_admin_service(
                authorization=None,
                x_service_key="a" * 48,
            )
        )
    except HTTPException as exc:
        assert exc.status_code == 401
        assert exc.detail["code"] == "SERVICE_TOKEN_REQUIRED"
    else:
        raise AssertionError("production must reject X-Service-Key fallback")


def test_signed_internal_token_is_scoped_to_admin(monkeypatch) -> None:
    calls = []

    def verify(token, *, trusted_keys, audience, allowed_subjects):
        calls.append((token, trusted_keys, audience, allowed_subjects))
        return allowed_subjects == {"admin"}

    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "trusted_service_public_keys", "configured-key")
    monkeypatch.setattr(admin_internal, "verify_service_token", verify)

    asyncio.run(
        admin_internal.verify_admin_service(
            authorization="Bearer signed-admin-token",
            x_service_key=None,
        )
    )

    assert calls == [
        (
            "signed-admin-token",
            "configured-key",
            "neomarket-b2b",
            {"admin"},
        )
    ]


def test_real_signed_service_token_accepts_admin_and_rejects_b2c(monkeypatch) -> None:
    signing_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = (
        signing_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    now = datetime.now(timezone.utc)

    def token(subject: str) -> str:
        return jwt.encode(
            {
                "sub": subject,
                "iss": "neomarket-services",
                "aud": "neomarket-b2b",
                "iat": now,
                "nbf": now,
                "exp": now + timedelta(minutes=5),
            },
            signing_key,
            algorithm="RS256",
            headers={"kid": "test-admin"},
        )

    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(
        settings,
        "trusted_service_public_keys",
        json.dumps({"test-admin": public_key}),
    )

    asyncio.run(
        admin_internal.verify_admin_service(
            authorization=f"Bearer {token('admin')}",
            x_service_key=None,
        )
    )
    try:
        asyncio.run(
            admin_internal.verify_admin_service(
                authorization=f"Bearer {token('b2c')}",
                x_service_key=None,
            )
        )
    except HTTPException as exc:
        assert exc.status_code == 401
    else:
        raise AssertionError("a signed B2C token must not access the Admin-only route")
