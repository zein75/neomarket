import pytest
from pydantic import ValidationError

from src.schemas.product import ProductImageCreate


def test_product_image_urls_require_public_https():
    assert ProductImageCreate(url="https://cdn.example/product.jpg").url
    with pytest.raises(ValidationError):
        ProductImageCreate(url="https://10.0.0.4/product.jpg")
    with pytest.raises(ValidationError, match="credentials"):
        ProductImageCreate(url="https://user:secret@cdn.example/product.jpg")


def test_product_image_urls_require_configured_media_cdn_in_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("MEDIA_PUBLIC_BASE_URL", "https://media.neomarket.test/api/v1/media/public")

    assert ProductImageCreate(url="https://media.neomarket.test/assets/product.jpg").url
    with pytest.raises(ValidationError, match="configured media CDN"):
        ProductImageCreate(url="https://cdn.example/product.jpg")


def test_product_image_urls_fail_closed_without_production_media_cdn(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("MEDIA_PUBLIC_BASE_URL", raising=False)

    with pytest.raises(ValidationError, match="configured media CDN"):
        ProductImageCreate(url="https://cdn.example/product.jpg")
    with pytest.raises(ValidationError):
        ProductImageCreate(url="http://cdn.example/product.jpg")
