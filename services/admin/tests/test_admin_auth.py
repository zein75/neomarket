from uuid import uuid4
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from jose import jwt

from src.api.deps import get_current_moderator
from src.core.config import settings


@pytest.mark.asyncio
async def test_production_moderator_requires_signed_bearer(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "secret_key", "test-secret")
    monkeypatch.setattr(settings, "algorithm", "HS256")
    moderator_id = uuid4()
    token = jwt.encode(
        {"sub": str(moderator_id), "role": "moderator", "iss": settings.jwt_issuer,
         "aud": settings.jwt_audience, "iat": datetime.now(timezone.utc),
         "nbf": datetime.now(timezone.utc), "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        settings.secret_key,
        algorithm=settings.algorithm,
        headers={"kid": settings.jwt_kid},
    )

    result = await get_current_moderator(authorization=f"Bearer {token}")
    assert result.id == moderator_id

    with pytest.raises(HTTPException) as error:
        await get_current_moderator(x_moderator_id=str(moderator_id))
    assert error.value.status_code == 401


@pytest.mark.asyncio
async def test_production_moderator_rejects_wrong_role(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "secret_key", "test-secret")
    token = jwt.encode(
        {"sub": str(uuid4()), "role": "seller", "iss": settings.jwt_issuer,
         "aud": settings.jwt_audience, "iat": datetime.now(timezone.utc),
         "nbf": datetime.now(timezone.utc), "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        settings.secret_key,
        algorithm=settings.algorithm,
        headers={"kid": settings.jwt_kid},
    )
    with pytest.raises(HTTPException) as error:
        await get_current_moderator(authorization=f"Bearer {token}")
    assert error.value.status_code == 403
