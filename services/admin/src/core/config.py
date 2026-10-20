import os
import math
from urllib.parse import urlsplit


class Settings:
    app_env: str = os.getenv("APP_ENV", "development")
    admin_allow_dev_auth: bool = os.getenv("ADMIN_ALLOW_DEV_AUTH", "false").strip().lower() in {"1", "true", "yes"}
    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@postgres:5432/neomarket",
    )
    b2b_base_url: str = os.getenv("B2B_BASE_URL", "http://b2b:8000")
    service_key: str = os.getenv("SERVICE_KEY", "dev-service-key")
    secret_key: str = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
    algorithm: str = os.getenv("JWT_ALGORITHM", "HS256")
    jwt_issuer: str = os.getenv("JWT_ISSUER", "neomarket-admin")
    jwt_audience: str = os.getenv("JWT_AUDIENCE", "neomarket-admin-api")
    jwt_kid: str = os.getenv("JWT_KID", "managed-v1")
    service_name: str = os.getenv("SERVICE_NAME", "admin")
    service_private_key: str = os.getenv("SERVICE_PRIVATE_KEY", "")
    trusted_service_public_keys: str = os.getenv("TRUSTED_SERVICE_PUBLIC_KEYS", "")
    oidc_issuer: str = os.getenv("OIDC_ISSUER", "")
    oidc_jwks_url: str = os.getenv("OIDC_JWKS_URL", "")
    # The issuer and JWKS URL remain the public HTTPS identifiers used for
    # token validation. In staging, the private Docker network can fetch the
    # same JWKS document through Keycloak's service name without requiring
    # public DNS or hairpin TLS.
    oidc_internal_base_url: str = os.getenv("OIDC_INTERNAL_BASE_URL", "").strip()
    oidc_audience: str = os.getenv("OIDC_AUDIENCE", "neomarket-admin-api")
    oidc_required_amr: str = os.getenv("OIDC_REQUIRED_AMR", "")
    oidc_required_acr: str = os.getenv("OIDC_REQUIRED_ACR", "")
    oidc_step_up_required_amr: str = os.getenv("OIDC_STEP_UP_REQUIRED_AMR", "")
    oidc_step_up_required_acr: str = os.getenv("OIDC_STEP_UP_REQUIRED_ACR", "")
    admin_step_up_max_age_seconds: int = int(os.getenv("ADMIN_STEP_UP_MAX_AGE_SECONDS", "300"))
    _admin_safety_hold_max_seconds_raw: str = os.getenv("ADMIN_SAFETY_HOLD_MAX_SECONDS", "").strip()
    admin_safety_hold_max_seconds: int | None = (
        int(_admin_safety_hold_max_seconds_raw) if _admin_safety_hold_max_seconds_raw else None
    )
    service_key_id: str = os.getenv("SERVICE_KEY_ID", "managed-v1")
    b2b_timeout_seconds: float = float(os.getenv("B2B_TIMEOUT_SECONDS", "3.0"))
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    admin_rate_limit_requests: int = int(os.getenv("ADMIN_RATE_LIMIT_REQUESTS", "120"))
    admin_rate_limit_window_seconds: int = int(os.getenv("ADMIN_RATE_LIMIT_WINDOW_SECONDS", "60"))
    moderation_claim_ttl_seconds: int = int(os.getenv("MODERATION_CLAIM_TTL_SECONDS", "900"))
    moderation_ticket_sla_seconds: int = int(os.getenv("MODERATION_TICKET_SLA_SECONDS", "86400"))
    complaint_case_sla_seconds: int = int(os.getenv("COMPLAINT_CASE_SLA_SECONDS", "86400"))
    audit_export_ttl_seconds: int = int(os.getenv("ADMIN_AUDIT_EXPORT_TTL_SECONDS", "900"))
    admin_session_idle_ttl_seconds: int = int(os.getenv("ADMIN_SESSION_IDLE_TTL_SECONDS", "1800"))
    admin_session_absolute_ttl_seconds: int = int(os.getenv("ADMIN_SESSION_ABSOLUTE_TTL_SECONDS", "28800"))
    admin_public_origin: str = os.getenv("ADMIN_PUBLIC_ORIGIN", os.getenv("NEOMARKET_PUBLIC_ORIGIN", ""))
    moderation_outbox_poll_interval_seconds: float = float(
        os.getenv("MODERATION_OUTBOX_POLL_INTERVAL_SECONDS", "1.0")
    )
    admin_run_outbox_worker: bool = os.getenv("ADMIN_RUN_OUTBOX_WORKER", "false").lower() == "true"

    @property
    def local_dev_auth_enabled(self) -> bool:
        return self.admin_allow_dev_auth and self.app_env.lower() in {"development", "dev", "test"}

    def validate_production(self) -> None:
        local_environment = self.app_env.lower() in {"development", "dev", "test"}
        if self.admin_allow_dev_auth and not local_environment:
            raise RuntimeError("ADMIN_ALLOW_DEV_AUTH may only be enabled in local development or tests")
        if not math.isfinite(self.b2b_timeout_seconds) or not 0.1 <= self.b2b_timeout_seconds <= 60:
            raise ValueError("B2B_TIMEOUT_SECONDS must be finite and between 0.1 and 60 seconds")
        if self.complaint_case_sla_seconds < 1:
            raise ValueError("COMPLAINT_CASE_SLA_SECONDS must be positive")
        if not 1 <= self.admin_rate_limit_requests <= 100_000:
            raise ValueError("ADMIN_RATE_LIMIT_REQUESTS must be between 1 and 100000")
        if not 1 <= self.admin_rate_limit_window_seconds <= 86400:
            raise ValueError("ADMIN_RATE_LIMIT_WINDOW_SECONDS must be between 1 and 86400")
        if self.moderation_claim_ttl_seconds < 1:
            raise ValueError("MODERATION_CLAIM_TTL_SECONDS must be positive")
        if self.moderation_ticket_sla_seconds < 1:
            raise ValueError("MODERATION_TICKET_SLA_SECONDS must be positive")
        if self.admin_safety_hold_max_seconds is not None and self.admin_safety_hold_max_seconds < 1:
            raise ValueError("ADMIN_SAFETY_HOLD_MAX_SECONDS must be positive when configured")
        if self.algorithm not in {"HS256", "HS384", "HS512"}:
            raise ValueError("JWT_ALGORITHM must be a supported HMAC JWT algorithm")
        if not 0.1 <= self.moderation_outbox_poll_interval_seconds <= 300:
            raise ValueError(
                "MODERATION_OUTBOX_POLL_INTERVAL_SECONDS must be between 0.1 and 300"
            )
        if not 60 <= self.audit_export_ttl_seconds <= 86400:
            raise ValueError("ADMIN_AUDIT_EXPORT_TTL_SECONDS must be between 60 and 86400")
        if not 300 <= self.admin_session_idle_ttl_seconds <= 86400:
            raise ValueError("ADMIN_SESSION_IDLE_TTL_SECONDS must be between 300 and 86400")
        if not 60 <= self.admin_step_up_max_age_seconds <= 1800:
            raise ValueError("ADMIN_STEP_UP_MAX_AGE_SECONDS must be between 60 and 1800")
        if not self.admin_session_idle_ttl_seconds <= self.admin_session_absolute_ttl_seconds <= 604800:
            raise ValueError("ADMIN_SESSION_ABSOLUTE_TTL_SECONDS must be between idle TTL and 604800")
        if not self.local_dev_auth_enabled:
            if len(self.service_key) < 32 or self.service_key.startswith("dev-"):
                raise RuntimeError("SERVICE_KEY must be at least 32 characters in production")
            if len(self.secret_key) < 32 or self.secret_key.startswith("dev-"):
                raise RuntimeError("SECRET_KEY must be at least 32 characters in production")
            if "postgres:postgres@" in self.database_url:
                raise RuntimeError("DATABASE_URL must not use default credentials")
            if not self.service_private_key or not self.trusted_service_public_keys:
                raise RuntimeError("SERVICE_PRIVATE_KEY and TRUSTED_SERVICE_PUBLIC_KEYS are required in production")
            if not self.redis_url.startswith(("redis://", "rediss://")):
                raise RuntimeError("REDIS_URL must be configured for Admin rate limiting")
            if not self.oidc_issuer or not self.oidc_jwks_url or not self.oidc_audience:
                raise RuntimeError("OIDC_ISSUER, OIDC_JWKS_URL and OIDC_AUDIENCE are required outside local development/test")
            if not self.oidc_required_amr.strip() and not self.oidc_required_acr.strip():
                raise RuntimeError("Configure OIDC_REQUIRED_AMR or OIDC_REQUIRED_ACR for the selected IdP")
            if not self.oidc_step_up_required_amr.strip() and not self.oidc_step_up_required_acr.strip():
                raise RuntimeError("Configure OIDC_STEP_UP_REQUIRED_AMR or OIDC_STEP_UP_REQUIRED_ACR for the selected IdP")
            public_origin = urlsplit(self.admin_public_origin)
            if (
                public_origin.scheme != "https"
                or not public_origin.netloc
                or public_origin.path not in {"", "/"}
                or public_origin.query
                or public_origin.fragment
                or public_origin.username
                or public_origin.password
            ):
                raise RuntimeError("ADMIN_PUBLIC_ORIGIN must be a configured HTTPS origin in production")
            if urlsplit(self.oidc_issuer).scheme != "https" or urlsplit(self.oidc_jwks_url).scheme != "https":
                raise RuntimeError("OIDC_ISSUER and OIDC_JWKS_URL must use HTTPS in production")
            if self.oidc_internal_base_url:
                internal = urlsplit(self.oidc_internal_base_url)
                if (
                    internal.scheme not in {"http", "https"}
                    or not internal.netloc
                    or internal.path not in {"", "/"}
                    or internal.query
                    or internal.fragment
                    or internal.username
                    or internal.password
                ):
                    raise RuntimeError("OIDC_INTERNAL_BASE_URL must be a host-only internal URL")
                if internal.scheme == "http" and internal.hostname not in {"keycloak", "gateway"}:
                    raise RuntimeError("HTTP OIDC_INTERNAL_BASE_URL is restricted to the private staging network")


settings = Settings()
settings.validate_production()
