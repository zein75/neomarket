"""Asymmetric service-to-service authentication helpers.

Production services sign short-lived RS256 tokens with their own private key;
receivers verify against an allow-list of public keys.  The legacy shared key
is retained only for local/development compatibility.
"""

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from jwt.exceptions import InvalidTokenError


def service_headers(
    settings: Any, *, audience: str, legacy_key: str | None = None
) -> dict[str, str]:
    private_key = getattr(settings, "service_private_key", "")
    if private_key:
        now = datetime.now(timezone.utc)
        token = jwt.encode(
            {
                "sub": getattr(settings, "service_name", "service"),
                "iss": "neomarket-services",
                "aud": audience,
                "iat": now,
                "nbf": now,
                "exp": now + timedelta(minutes=5),
            },
            private_key,
            algorithm="RS256",
            headers={"kid": getattr(settings, "service_key_id", "managed-v1")},
        )
        return {"Authorization": f"Bearer {token}"}
    if str(getattr(settings, "app_env", "development")).lower() in {"production", "prod"}:
        raise RuntimeError("SERVICE_PRIVATE_KEY is required in production; legacy X-Service-Key is disabled")
    return {"X-Service-Key": legacy_key or settings.service_key}


def verify_service_token(
    token: str,
    *,
    trusted_keys: str,
    audience: str,
    allowed_subjects: set[str],
) -> bool:
    try:
        header = jwt.get_unverified_header(token)
        keys = json.loads(trusted_keys or "{}")
        key = keys.get(header.get("kid"))
        if not key:
            return False
        payload = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            issuer="neomarket-services",
            audience=audience,
            options={"require": ["sub", "iat", "nbf", "exp"]},
        )
        return str(payload.get("sub")) in allowed_subjects
    except (InvalidTokenError, ValueError, TypeError, json.JSONDecodeError):
        return False
