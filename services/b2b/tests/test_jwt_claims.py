import base64
import json
from uuid import uuid4
from datetime import datetime, timedelta, timezone

from jose import jwt

from src.core import security
from src.core.config import settings


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
