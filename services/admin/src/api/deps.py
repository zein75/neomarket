from types import SimpleNamespace
from uuid import UUID
from secrets import compare_digest
from jose import JWTError, jwt
from fastapi import Header, HTTPException, status
from src.core.config import settings
from shared.utils.service_auth import verify_service_token


async def get_current_moderator(
    x_moderator_id: str | None = Header(default=None, alias="X-Moderator-Id"),
    authorization: str | None = Header(default=None),
) -> SimpleNamespace:
    if settings.app_env.lower() in {"production", "prod"}:
        if not isinstance(authorization, str) or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
        token = authorization[7:].strip()
        try:
            header = jwt.get_unverified_header(token)
            if header.get("kid") != settings.jwt_kid:
                raise JWTError("Unknown JWT key id")
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
        except JWTError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid bearer token") from exc
        subject = payload.get("sub")
        role = payload.get("role")
        if not subject or role not in {"moderator", "admin"}:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Moderator role required")
        try:
            return SimpleNamespace(id=UUID(str(subject)))
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid moderator subject") from exc
    if not x_moderator_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing moderator identity",
        )
    try:
        moderator_id = UUID(x_moderator_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid moderator identity",
        )
    return SimpleNamespace(id=moderator_id)


async def verify_service_key(
    x_service_key: str | None = Header(default=None, alias="X-Service-Key"),
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> None:
    if authorization and authorization.lower().startswith("bearer ") and settings.trusted_service_public_keys:
        if verify_service_token(authorization[7:].strip(), trusted_keys=settings.trusted_service_public_keys, audience="neomarket-admin", allowed_subjects={"b2b", "b2c"}):
            return
    if not x_service_key or not compare_digest(x_service_key, settings.service_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "message": "Invalid service key"},
        )
