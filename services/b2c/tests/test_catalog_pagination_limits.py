from fastapi import HTTPException

import pytest

from src.api.routers import catalog as catalog_router
from src.api.routers.catalog import list_catalog, list_products


@pytest.mark.asyncio
async def test_catalog_rejects_unbounded_offset():
    with pytest.raises(HTTPException):
        await list_products(offset=10_001, sort="popularity")


@pytest.mark.asyncio
async def test_cursor_catalog_returns_opaque_next_cursor(monkeypatch):
    class FakeCatalogService:
        async def list_products(self, **kwargs):
            assert kwargs == {"limit": 2, "offset": 0}
            return {"items": [{"id": "one"}, {"id": "two"}], "total_count": 3}

    monkeypatch.setattr(catalog_router, "CatalogService", FakeCatalogService)
    result = await list_catalog(limit=2)

    assert result["items"] == [{"id": "one"}, {"id": "two"}]
    assert result["page"]["has_more"] is True
    assert result["page"]["next_cursor"]


@pytest.mark.asyncio
async def test_cursor_catalog_rejects_invalid_cursor():
    with pytest.raises(HTTPException) as error:
        await list_catalog(cursor="not-a-cursor")
    assert error.value.status_code == 422
    assert error.value.detail["code"] == "INVALID_CURSOR"
