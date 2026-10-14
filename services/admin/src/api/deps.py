from types import SimpleNamespace
from uuid import UUID
from secrets import compare_digest
from jose import JWTError, jwt
import httpx
import time
from fastapi import Header, HTTPException, status
from src.core.config import settings
from shared.utils.service_auth import verify_service_token

_jwks_cache: tuple[float, dict[str, object]] | None = None


async def _oidc_keys() -> dict[str, object]:
    global _jwks_cache
    now = time.monotonic()
    if _jwks_cache and _jwks_cache[0] > now:
        return _jwks_cache[1]
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(settings.oidc_jwks_url)
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="OIDC provider unavailable") from exc
    keys = {str(item["kid"]): item for item in payload.get("keys", []) if item.get("kid")}
    if not keys:
        raise HTTPException(status_code=503, detail="OIDC provider returned no signing keys")
    _jwks_cache = (now + 300, keys)
    return keys


async def get_current_moderator(
    x_moderator_id: str | None = Header(default=None, alias="X-Moderator-Id"),
    authorization: str | None = Header(default=None),
) -> SimpleNamespace:
    if settings.app_env.lower() in {"production", "prod"}:
        if not isinstance(authorization, str) or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
        token = authorization[7:].strip()
        if settings.oidc_issuer and settings.oidc_jwks_url:
            try:
                header = jwt.get_unverified_header(token)
                key = (await _oidc_keys()).get(str(header.get("kid")))
                if not key:
                    raise JWTError("Unknown OIDC key id")
                payload = jwt.decode(
                    token,
                    key,
                    algorithms=["RS256", "RS384", "RS512"],
                    issuer=settings.oidc_issuer,
                    audience=settings.oidc_audience,
                    options={"require_sub": True, "require_iat": True, "require_nbf": True, "require_exp": True},
                )
                amr = payload.get("amr", [])
                if not isinstance(amr, list) or settings.oidc_required_amr not in amr:
                    raise HTTPException(status_code=403, detail="MFA claim required")
                subject = payload.get("sub")
                roles = payload.get("roles", payload.get("role", []))
                if isinstance(roles, str):
                    roles = [roles]
                if not subject or not isinstance(roles, list) or not ({"moderator", "admin"} & set(roles)):
                    raise HTTPException(status_code=403, detail="Moderator role required")
                return SimpleNamespace(id=UUID(str(subject)))
            except HTTPException:
                raise
            except (JWTError, ValueError, TypeError) as exc:
                raise HTTPException(status_code=401, detail="Invalid OIDC bearer token") from exc
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
    if settings.app_env.lower() in {"production", "prod"}:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "SERVICE_TOKEN_REQUIRED", "message": "Signed service token is required"},
        )
    if not x_service_key or not compare_digest(x_service_key, settings.service_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "message": "Invalid service key"},
        )
