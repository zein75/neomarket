from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from src.api.routers import products as products_router


@pytest.mark.asyncio
async def test_seller_catalog_cursor_page(monkeypatch):
    class FakeService:
        def __init__(self, _db):
            pass

        async def list_for_seller_cabinet(self, **kwargs):
            assert kwargs["offset"] == 0
            return SimpleNamespace(items=[{"id": "one"}], total_count=2)

    monkeypatch.setattr(products_router, "ProductService", FakeService)
    result = await products_router.list_seller_products_cursor(
        current_seller=SimpleNamespace(id=uuid4()), db=object(), limit=1
    )

    assert result["items"] == [{"id": "one"}]
    assert result["page"]["has_more"] is True
    assert result["page"]["next_cursor"]


@pytest.mark.asyncio
async def test_seller_catalog_rejects_invalid_cursor():
    with pytest.raises(HTTPException) as error:
        await products_router.list_seller_products_cursor(
            cursor="invalid", current_seller=SimpleNamespace(id=uuid4()), db=object()
        )
    assert error.value.status_code == 422
    assert error.value.detail["code"] == "INVALID_CURSOR"
