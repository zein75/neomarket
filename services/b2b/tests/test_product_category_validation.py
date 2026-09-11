from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from src.schemas.product import Characteristic, ProductCreate, ProductImageCreate
from src.services import product_service as product_service_module
from src.services.product_service import ProductService


class FakeProductRepository:
    def __init__(self, session: object) -> None:
        self.session = session
        self.create_called = False

    async def category_exists(self, category_id):
        return False

    async def create_product(self, **kwargs):
        self.create_called = True
        raise AssertionError("product must not be created for unknown category")


@pytest.fixture(autouse=True)
def patch_repo(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        product_service_module,
        "ProductRepository",
        FakeProductRepository,
    )


@pytest.mark.asyncio
async def test_create_product_unknown_category_returns_400() -> None:
    service = ProductService(SimpleNamespace())
    payload = ProductCreate(
        title="Wireless keyboard",
        description="Low-profile keyboard",
        category_id=uuid4(),
        images=[
            ProductImageCreate(
                url="https://cdn.neomarket.test/products/keyboard.jpg",
                ordering=0,
            )
        ],
        characteristics=[Characteristic(name="layout", value="US")],
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.create(uuid4(), payload)

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == {
        "code": "INVALID_REQUEST",
        "message": "Category not found",
    }
    assert service.repo.create_called is False
