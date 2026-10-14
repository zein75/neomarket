from types import SimpleNamespace

import pytest

from shared.utils.service_auth import service_headers


def test_production_never_falls_back_to_legacy_service_key() -> None:
    settings = SimpleNamespace(
        app_env="production",
        service_private_key="",
        service_key="a" * 64,
    )
    with pytest.raises(RuntimeError, match="legacy X-Service-Key is disabled"):
        service_headers(settings, audience="neomarket-b2c")


def test_development_keeps_legacy_compatibility() -> None:
    settings = SimpleNamespace(
        app_env="development",
        service_private_key="",
        service_key="dev-key",
    )
    assert service_headers(settings, audience="neomarket-b2c") == {"X-Service-Key": "dev-key"}
