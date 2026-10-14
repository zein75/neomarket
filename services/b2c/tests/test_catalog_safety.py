import pytest

from src.services.catalog_service import CatalogService


@pytest.mark.asyncio
async def test_facets_stop_when_upstream_offset_does_not_advance(monkeypatch):
    calls = 0

    async def stuck_page(**_kwargs):
        nonlocal calls
        calls += 1
        return {"items": [{"id": "one"}], "total_count": 100, "limit": 0, "offset": 0}

    service = CatalogService()
    monkeypatch.setattr(service, "_load_products", stuck_page)
    products = await service._load_all_products()

    assert products == [{"id": "one"}]
    assert calls == 1
