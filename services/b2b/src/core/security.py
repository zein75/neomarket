from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext

from .config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(subject: str) -> str:
    now = datetime.now(timezone.utc)
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    return jwt.encode(
        {
            "sub": subject,
            "iat": now,
            "nbf": now,
            "exp": expire,
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
        },
        settings.secret_key,
        algorithm=settings.algorithm,
        headers={"kid": settings.jwt_kid},
    )


def decode_access_token(token: str) -> str | None:
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
                "require_sub": True,
                "require_iat": True,
                "require_nbf": True,
                "require_exp": True,
            },
        )
        subject = payload.get("sub")
        return str(subject) if subject else None
    except JWTError:
        return None
