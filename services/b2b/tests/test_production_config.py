import pytest

from src.core.config import Settings


def test_production_rejects_default_credentials_and_secrets() -> None:
    with pytest.raises(ValueError, match="SECRET_KEY"):
        Settings(app_env="production")


def test_production_accepts_explicit_secrets_and_database_url() -> None:
    settings = Settings(
        app_env="production",
        secret_key="a" * 32,
        service_key="b" * 32,
        service_private_key="test-private-key",
        trusted_service_public_keys='{"managed-v1":"test-public-key"}',
        database_url="postgresql+asyncpg://runtime:strong-password@postgres:5432/b2b",
        email_smtp_host="smtp.neomarket.test",
        email_from_address="seller@neomarket.test",
        seller_verification_url="https://seller.neomarket.test/verify-email",
        seller_invitation_url="https://seller.neomarket.test/team/accept-invite",
        media_upload_signing_secret="c" * 32,
        media_public_base_url="https://cdn.neomarket.test/api/v1/media/public",
    )
    assert settings.app_env == "production"
