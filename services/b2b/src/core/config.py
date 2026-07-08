from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5434/b2b"
    redis_url: str = "redis://localhost:6379"

    secret_key: str = "dev-secret-key-change-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    moderation_url: str = "http://moderation:8000"
    service_key: str = "dev-service-key-change-in-production"
    moderation_timeout_seconds: float = 3.0


settings = Settings()
