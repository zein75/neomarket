from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5434/b2c"
    redis_url: str = "redis://localhost:6379"
    app_env: str = "development"

    secret_key: str = "dev-secret-key-change-in-production"
    algorithm: str = "HS256"
    jwt_issuer: str = "neomarket-b2c"
    jwt_audience: str = "neomarket-b2c-api"
    jwt_kid: str = "managed-v1"
    access_token_expire_minutes: int = 15

    b2b_base_url: str = "http://localhost:8002"
    service_key: str = "dev-service-key-change-in-production"
    service_name: str = "b2c"
    service_private_key: str = ""
    trusted_service_public_keys: str = ""
    service_key_id: str = "managed-v1"
    recovery_worker_enabled: bool = True
    recovery_worker_poll_interval_seconds: float = 30.0

    @model_validator(mode="after")
    def validate_production_secrets(self) -> "Settings":
        if self.algorithm not in {"HS256", "HS384", "HS512"}:
            raise ValueError("ALGORITHM must be a supported HMAC JWT algorithm")
        if not 1 <= self.access_token_expire_minutes <= 15:
            raise ValueError("ACCESS_TOKEN_EXPIRE_MINUTES must be between 1 and 15")
        if not 0.1 <= self.recovery_worker_poll_interval_seconds <= 300:
            raise ValueError("RECOVERY_WORKER_POLL_INTERVAL_SECONDS must be between 0.1 and 300")
        if self.app_env.lower() in {"production", "prod"}:
            if len(self.secret_key) < 32 or self.secret_key.startswith("dev-"):
                raise ValueError("SECRET_KEY must be at least 32 characters in production")
            if len(self.service_key) < 32 or self.service_key.startswith("dev-"):
                raise ValueError("SERVICE_KEY must be at least 32 characters in production")
            if "postgres:postgres@" in self.database_url:
                raise ValueError("DATABASE_URL must not use default credentials")
            if not self.jwt_kid.strip():
                raise ValueError("JWT_KID must identify a managed production key")
            if not self.service_private_key or not self.trusted_service_public_keys:
                raise ValueError("SERVICE_PRIVATE_KEY and TRUSTED_SERVICE_PUBLIC_KEYS are required in production")
        return self


settings = Settings()
