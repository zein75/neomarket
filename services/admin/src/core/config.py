import os


class Settings:
    app_env: str = os.getenv("APP_ENV", "development")
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
    service_key_id: str = os.getenv("SERVICE_KEY_ID", "managed-v1")
    b2b_timeout_seconds: float = float(os.getenv("B2B_TIMEOUT_SECONDS", "3.0"))
    moderation_claim_ttl_seconds: int = int(os.getenv("MODERATION_CLAIM_TTL_SECONDS", "900"))
    moderation_outbox_poll_interval_seconds: float = float(
        os.getenv("MODERATION_OUTBOX_POLL_INTERVAL_SECONDS", "1.0")
    )

    def validate_production(self) -> None:
        if self.algorithm not in {"HS256", "HS384", "HS512"}:
            raise ValueError("JWT_ALGORITHM must be a supported HMAC JWT algorithm")
        if not 0.1 <= self.moderation_outbox_poll_interval_seconds <= 300:
            raise ValueError(
                "MODERATION_OUTBOX_POLL_INTERVAL_SECONDS must be between 0.1 and 300"
            )
        if self.app_env.lower() in {"production", "prod"}:
            if len(self.service_key) < 32 or self.service_key.startswith("dev-"):
                raise RuntimeError("SERVICE_KEY must be at least 32 characters in production")
            if len(self.secret_key) < 32 or self.secret_key.startswith("dev-"):
                raise RuntimeError("SECRET_KEY must be at least 32 characters in production")
            if "postgres:postgres@" in self.database_url:
                raise RuntimeError("DATABASE_URL must not use default credentials")
            if not self.service_private_key or not self.trusted_service_public_keys:
                raise RuntimeError("SERVICE_PRIVATE_KEY and TRUSTED_SERVICE_PUBLIC_KEYS are required in production")


settings = Settings()
settings.validate_production()
