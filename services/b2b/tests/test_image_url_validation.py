import pytest
from pydantic import ValidationError

from src.schemas.sku import SKUImageCreate


def test_image_urls_require_https():
    assert SKUImageCreate(url="https://cdn.example/image.jpg").url.startswith("https://")
    with pytest.raises(ValidationError):
        SKUImageCreate(url="http://internal/image.jpg")
    with pytest.raises(ValidationError):
        SKUImageCreate(url="https://127.0.0.1/image.jpg")
    with pytest.raises(ValidationError):
        SKUImageCreate(url="https://catalog.local/image.jpg")


def test_image_write_schema_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        SKUImageCreate(url="https://cdn.example/image.jpg", internal_path="/etc/passwd")


def test_sku_image_urls_require_configured_media_cdn_in_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("MEDIA_PUBLIC_BASE_URL", "https://media.neomarket.test/api/v1/media/public")

    assert SKUImageCreate(url="https://media.neomarket.test/assets/sku.jpg").url
    with pytest.raises(ValidationError, match="configured media CDN"):
        SKUImageCreate(url="https://cdn.example/image.jpg")
