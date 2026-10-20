import asyncio
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from src.api.routers.products import list_products
from src.clients.b2b_client import B2BClient


def test_admin_product_registry_forwards_server_search_and_cursor(monkeypatch):
    product_id = '6f187a85-4051-4e64-a97b-35f3bf99f98d'
    seller_id = '4ab9e49a-42f3-4494-9650-cc7c6edbdacb'
    calls = []

    async def get_internal_json(_self, path):
        calls.append(path)
        return {
            'items': [{
                'product_id': product_id, 'seller_id': seller_id,
                'current_revision': 4, 'published_revision': 3,
                'visible': False, 'visibility_reasons': ['NO_ACTIVE_SKU'],
            }],
            'page': {'has_more': False, 'next_cursor': None},
        }

    monkeypatch.setattr(B2BClient, 'get_internal_json', get_internal_json)
    result = asyncio.run(list_products(
        cursor='prior-cursor', limit=25, search='  bracket  ',
        _=SimpleNamespace(id='staff-id'),
    ))

    query = parse_qs(urlparse(calls[0]).query)
    assert query == {'limit': ['25'], 'cursor': ['prior-cursor'], 'search': ['bracket']}
    assert str(result.items[0].id) == product_id
    assert result.items[0].visible is False
    assert result.page.next_cursor is None
