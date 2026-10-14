import pytest
from pydantic import ValidationError

from src.schemas.product import ProductImageCreate


def test_product_image_urls_require_public_https():
    assert ProductImageCreate(url="https://cdn.example/product.jpg").url
    with pytest.raises(ValidationError):
        ProductImageCreate(url="https://10.0.0.4/product.jpg")
    with pytest.raises(ValidationError):
        ProductImageCreate(url="http://cdn.example/product.jpg")
