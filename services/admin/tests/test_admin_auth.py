import json

from fastapi import HTTPException
from starlette.requests import Request

import pytest

from src.api.deps import _oidc_jwks_request, get_current_moderator
from src.main import http_exception_handler


class FakeSession:
    def __init__(self):
        self.added = []

    def add(self, item):
        self.added.append(item)

    async def commit(self):
        return None

    async def rollback(self):
        return None


def test_oidc_jwks_fetch_uses_private_keycloak_but_keeps_public_host(monkeypatch):
    from src.core.config import settings

    monkeypatch.setattr(
        settings,
        "oidc_jwks_url",
        "https://keycloak.neomarket.test/realms/neomarket-staging/protocol/openid-connect/certs",
    )
    monkeypatch.setattr(settings, "oidc_internal_base_url", "http://keycloak:8080")

    url, headers = _oidc_jwks_request()

    assert url == "http://keycloak:8080/realms/neomarket-staging/protocol/openid-connect/certs"
    assert headers == {
        "Host": "keycloak.neomarket.test",
        "X-Forwarded-Host": "keycloak.neomarket.test",
        "X-Forwarded-Proto": "https",
    }


def _request(path="/admin/v1/moderation/tickets"):
    return Request({
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "https",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "server": ("test", 443),
        "path_params": {},
        "app": None,
    })


@pytest.mark.asyncio
async def test_production_rejects_bearer_token_for_principal_api_and_audits(monkeypatch):
    from src.core.config import settings

    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "admin_allow_dev_auth", True)
    db = FakeSession()

    with pytest.raises(HTTPException) as error:
        await get_current_moderator(
            request=_request(),
            authorization="Bearer forged-or-stale-token",
            db=db,
        )

    assert error.value.status_code == 401
    assert len(db.added) == 1
    audit = db.added[0]
    assert audit.action == "ADMIN_AUTH_FAILED"
    assert audit.details == {
        "auth_kind": "staff",
        "method": "GET",
        "path": "/admin/v1/moderation/tickets",
        "status_code": 401,
    }


@pytest.mark.asyncio
async def test_production_ignores_development_moderator_header(monkeypatch):
    from src.core.config import settings

    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "admin_allow_dev_auth", True)
    db = FakeSession()

    with pytest.raises(HTTPException) as error:
        await get_current_moderator(
            request=_request(),
            x_moderator_id="8ea900dc-69d0-43b5-9af8-202c907be953",
            db=db,
        )

    assert error.value.status_code == 401


@pytest.mark.asyncio
async def test_http_errors_use_strict_problem_json_contract_and_retry_header():
    request = _request("/admin/v1/operations")
    request.state.request_id = "request-problem-test"

    response = await http_exception_handler(
        request,
        HTTPException(
            status_code=429,
            detail={"code": "RATE_LIMITED", "message": "Too many requests"},
        ),
    )

    payload = json.loads(response.body)
    assert response.status_code == 429
    assert response.media_type == "application/problem+json"
    assert response.headers["retry-after"] == "1"
    assert payload == {
        "type": "urn:neomarket:problem:rate_limited",
        "title": "Too Many Requests",
        "status": 429,
        "detail": "Too many requests",
        "code": "RATE_LIMITED",
        "instance": "/admin/v1/operations",
        "request_id": "request-problem-test",
        "retryable": True,
    }


@pytest.mark.asyncio
async def test_staging_configuration_disables_dev_auth_and_rejects_moderator_header(
    monkeypatch,
):
    from src.core.config import settings

    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "admin_allow_dev_auth", False)
    assert settings.local_dev_auth_enabled is False

    db = FakeSession()
    with pytest.raises(HTTPException) as error:
        await get_current_moderator(
            request=_request(),
            x_moderator_id="8ea900dc-69d0-43b5-9af8-202c907be953",
            db=db,
        )

    assert error.value.status_code == 401
    assert len(db.added) == 1
    assert db.added[0].action == "ADMIN_AUTH_FAILED"
    assert db.added[0].details["status_code"] == 401

    monkeypatch.setattr(settings, "admin_allow_dev_auth", True)
    with pytest.raises(RuntimeError, match="ADMIN_ALLOW_DEV_AUTH may only be enabled"):
        settings.validate_production()
