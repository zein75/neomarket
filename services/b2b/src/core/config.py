from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5434/b2b"
    database_connect_timeout_seconds: float = 3.0
    redis_url: str = "redis://localhost:6379"
    app_env: str = "development"

    secret_key: str = "dev-secret-key-change-in-production"
    algorithm: str = "HS256"
    jwt_issuer: str = "neomarket-b2b"
    jwt_audience: str = "neomarket-b2b-api"
    jwt_kid: str = "managed-v1"
    access_token_expire_minutes: int = 15
    login_rate_limit_ip_attempts: int = 20
    login_rate_limit_email_attempts: int = 8
    login_rate_limit_window_seconds: int = 900
    email_smtp_host: str = ""
    email_smtp_port: int = 587
    email_smtp_username: str = ""
    email_smtp_password: str = ""
    email_smtp_mode: str = "starttls"
    email_from_address: str = ""
    seller_verification_url: str = "http://localhost:3002/verify-email"
    seller_invitation_url: str = "http://localhost:3002/team/accept-invite"
    seller_invitation_ttl_hours: int = 72

    moderation_url: str = "http://moderation:8000"
    b2c_url: str = "http://b2c:8000"
    service_key: str = "dev-service-key-change-in-production"
    local_carrier_webhook_secret: str = "dev-local-carrier-webhook-secret"
    service_name: str = "b2b"
    service_private_key: str = ""
    trusted_service_public_keys: str = ""
    service_key_id: str = "managed-v1"
    moderation_timeout_seconds: float = 3.0
    b2c_timeout_seconds: float = 3.0
    outbox_poll_interval_seconds: float = 1.0
    media_storage_root: str = "/app/media"
    media_upload_signing_secret: str = ""
    media_public_base_url: str = "http://127.0.0.1:8002/api/v1/media/public"
    media_scanner_host: str = "localhost"
    media_scanner_port: int = 3310
    media_scan_poll_interval_seconds: float = 1.0
    media_upload_rate_limit_requests: int = 30
    media_upload_rate_limit_window_seconds: int = 3600
    inventory_export_poll_interval_seconds: float = 2.0
    inventory_export_processing_lease_seconds: int = 300
    inventory_export_ttl_seconds: int = 900
    inventory_export_max_rows: int = 100_000
    inventory_export_rate_limit_requests: int = 5
    inventory_export_rate_limit_window_seconds: int = 3600

    @model_validator(mode="after")
    def validate_production_secrets(self) -> "Settings":
        if self.algorithm not in {"HS256", "HS384", "HS512"}:
            raise ValueError("ALGORITHM must be a supported HMAC JWT algorithm")
        if not 1 <= self.access_token_expire_minutes <= 15:
            raise ValueError("ACCESS_TOKEN_EXPIRE_MINUTES must be between 1 and 15")
        if not 1 <= self.login_rate_limit_ip_attempts <= 1000:
            raise ValueError("LOGIN_RATE_LIMIT_IP_ATTEMPTS must be between 1 and 1000")
        if not 1 <= self.login_rate_limit_email_attempts <= 1000:
            raise ValueError("LOGIN_RATE_LIMIT_EMAIL_ATTEMPTS must be between 1 and 1000")
        if not 1 <= self.login_rate_limit_window_seconds <= 86400:
            raise ValueError("LOGIN_RATE_LIMIT_WINDOW_SECONDS must be between 1 and 86400")
        if not 1 <= self.email_smtp_port <= 65535:
            raise ValueError("EMAIL_SMTP_PORT must be between 1 and 65535")
        if not 0.1 <= self.database_connect_timeout_seconds <= 30:
            raise ValueError("DATABASE_CONNECT_TIMEOUT_SECONDS must be between 0.1 and 30")
        if not 1 <= self.seller_invitation_ttl_hours <= 720:
            raise ValueError("SELLER_INVITATION_TTL_HOURS must be between 1 and 720")
        if self.email_smtp_mode not in {"starttls", "ssl", "plain"}:
            raise ValueError("EMAIL_SMTP_MODE must be starttls, ssl, or plain")
        if not 0.1 <= self.outbox_poll_interval_seconds <= 300:
            raise ValueError("OUTBOX_POLL_INTERVAL_SECONDS must be between 0.1 and 300")
        if not 1 <= self.media_scanner_port <= 65535:
            raise ValueError("MEDIA_SCANNER_PORT must be between 1 and 65535")
        if not 0.1 <= self.media_scan_poll_interval_seconds <= 300:
            raise ValueError("MEDIA_SCAN_POLL_INTERVAL_SECONDS must be between 0.1 and 300")
        if not 1 <= self.media_upload_rate_limit_requests <= 1000:
            raise ValueError("MEDIA_UPLOAD_RATE_LIMIT_REQUESTS must be between 1 and 1000")
        if not 60 <= self.media_upload_rate_limit_window_seconds <= 86400:
            raise ValueError("MEDIA_UPLOAD_RATE_LIMIT_WINDOW_SECONDS must be between 60 and 86400")
        if not 0.1 <= self.inventory_export_poll_interval_seconds <= 300:
            raise ValueError("INVENTORY_EXPORT_POLL_INTERVAL_SECONDS must be between 0.1 and 300")
        if not 30 <= self.inventory_export_processing_lease_seconds <= 3600:
            raise ValueError("INVENTORY_EXPORT_PROCESSING_LEASE_SECONDS must be between 30 and 3600")
        if not 60 <= self.inventory_export_ttl_seconds <= 86400:
            raise ValueError("INVENTORY_EXPORT_TTL_SECONDS must be between 60 and 86400")
        if not 1 <= self.inventory_export_max_rows <= 1_000_000:
            raise ValueError("INVENTORY_EXPORT_MAX_ROWS must be between 1 and 1000000")
        if not 1 <= self.inventory_export_rate_limit_requests <= 100:
            raise ValueError("INVENTORY_EXPORT_RATE_LIMIT_REQUESTS must be between 1 and 100")
        if not 60 <= self.inventory_export_rate_limit_window_seconds <= 86400:
            raise ValueError("INVENTORY_EXPORT_RATE_LIMIT_WINDOW_SECONDS must be between 60 and 86400")
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
            if not self.email_smtp_host.strip() or not self.email_from_address.strip():
                raise ValueError("EMAIL_SMTP_HOST and EMAIL_FROM_ADDRESS are required in production")
            if self.email_smtp_mode == "plain":
                raise ValueError("EMAIL_SMTP_MODE=plain is not allowed in production")
            if not self.seller_verification_url.startswith("https://"):
                raise ValueError("SELLER_VERIFICATION_URL must use HTTPS in production")
            if not self.seller_invitation_url.startswith("https://"):
                raise ValueError("SELLER_INVITATION_URL must use HTTPS in production")
            if len(self.media_upload_signing_secret) < 32:
                raise ValueError("MEDIA_UPLOAD_SIGNING_SECRET must be at least 32 characters in production")
            if not self.media_public_base_url.startswith("https://"):
                raise ValueError("MEDIA_PUBLIC_BASE_URL must use HTTPS in production")
        return self


settings = Settings()
