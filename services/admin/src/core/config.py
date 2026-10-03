import os


class Settings:
    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@postgres:5432/neomarket",
    )
    b2b_base_url: str = os.getenv("B2B_BASE_URL", "http://b2b:8000")
    service_key: str = os.getenv("SERVICE_KEY", "dev-service-key")
    b2b_timeout_seconds: float = float(os.getenv("B2B_TIMEOUT_SECONDS", "3.0"))


settings = Settings()
