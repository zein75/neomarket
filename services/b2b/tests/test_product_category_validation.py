from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from src.schemas.product import Characteristic, ProductCreate, ProductImageCreate
from src.services.product_service import ProductService


@pytest.mark.asyncio
async def test_create_product_unknown_category_returns_404() -> None:
    session = SimpleNamespace(get=AsyncMock(return_value=None))
    service = ProductService(session)
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

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == {
        "code": "CATEGORY_NOT_FOUND",
        "message": "Category not found",
    }
    session.get.assert_awaited_once()
