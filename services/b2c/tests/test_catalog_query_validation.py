from fastapi import HTTPException

import pytest

from src.api.routers.catalog import list_products


@pytest.mark.asyncio
async def test_catalog_rejects_unknown_sort():
    with pytest.raises(HTTPException) as error:
        await list_products(sort="random")
    assert error.value.status_code == 400
    assert error.value.detail["code"] == "INVALID_SORT"


@pytest.mark.asyncio
async def test_catalog_rejects_inverted_price_range():
    with pytest.raises(HTTPException) as error:
        await list_products(price_min=100, price_max=10, sort="popularity")
    assert error.value.status_code == 400
    assert error.value.detail["code"] == "INVALID_PRICE_RANGE"


@pytest.mark.asyncio
async def test_catalog_accepts_newest_sort_alias(monkeypatch):
    class FakeCatalogService:
        async def list_products(self, **kwargs):
            assert kwargs["sort"] == "new"
            return {"items": [], "total_count": 0, "limit": 20, "offset": 0}

    monkeypatch.setattr("src.api.routers.catalog.CatalogService", FakeCatalogService)
    await list_products(sort="newest")
