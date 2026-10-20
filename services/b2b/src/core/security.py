from datetime import datetime, timedelta, timezone

import jwt
from jwt.exceptions import InvalidTokenError
from passlib.context import CryptContext

from .config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(
    subject: str, session_version: int = 0, *, seller_id: str | None = None
) -> str:
    now = datetime.now(timezone.utc)
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    payload: dict[str, object] = {
            "sub": subject,
            "iat": now,
            "nbf": now,
            "exp": expire,
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "session_version": session_version,
        }
    if seller_id is not None:
        payload["seller_id"] = seller_id
    return jwt.encode(
        payload,
        settings.secret_key,
        algorithm=settings.algorithm,
        headers={"kid": settings.jwt_kid},
    )


def decode_access_token_payload(token: str) -> dict[str, object] | None:
    try:
        header = jwt.get_unverified_header(token)
        if header.get("kid") != settings.jwt_kid:
            return None
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.algorithm],
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
            options={
                "require": ["sub", "iat", "nbf", "exp"],
            },
        )
        return payload if isinstance(payload, dict) else None
    except InvalidTokenError:
        return None


def decode_access_token(token: str) -> str | None:
    payload = decode_access_token_payload(token)
    subject = payload.get("sub") if payload else None
    return str(subject) if subject else None
