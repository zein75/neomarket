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
