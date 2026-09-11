from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.clients import b2c as b2c_client_module
from src.clients.b2c import B2CClient


@pytest.mark.asyncio
async def test_product_blocked_uses_canonical_b2c_event_contract(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class Response:
        status_code = 204

        def raise_for_status(self) -> None:
            return None

    class AsyncClient:
        def __init__(self, **_: object) -> None:
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def post(self, url: str, *, json: dict[str, object], headers: dict[str, str]):
            captured.update(url=url, json=json, headers=headers)
            return Response()

    monkeypatch.setattr(b2c_client_module.httpx, "AsyncClient", AsyncClient)
    product = SimpleNamespace(id=uuid4(), status="BLOCKED", skus=[SimpleNamespace(id=uuid4())])

    await B2CClient(base_url="http://b2c", service_key="service-key").send_product_blocked(product)

    assert captured["url"] == "http://b2c/api/v1/b2b/events"
    assert captured["headers"] == {"X-Service-Key": "service-key"}
    payload = captured["json"]
    assert payload["event_type"] == "PRODUCT_BLOCKED"
    assert payload["payload"] == {
        "product_id": str(product.id),
        "sku_ids": [str(product.skus[0].id)],
        "reason": "BLOCKED",
    }
