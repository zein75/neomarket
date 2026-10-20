import asyncio

import httpx
import pytest

from src.clients import b2c


def test_b2c_outbox_routes_brand_envelope_to_taxonomy_receiver(monkeypatch):
    requests = []

    class Response:
        status_code = 202

        def raise_for_status(self):
            return None

    class Client:
        def __init__(self, *, timeout):
            assert timeout > 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, *, json, headers):
            requests.append((url, json, headers))
            return Response()

    monkeypatch.setattr(b2c.httpx, "AsyncClient", Client)
    event = {
        "schema_version": 1,
        "event_type": "brand.merged.v1",
        "producer": "b2b",
        "aggregate_type": "brand",
    }

    asyncio.run(b2c.B2CClient(base_url="http://b2c", service_key="fixture").send_outbox_event(event))

    assert requests[0][0] == "http://b2c/internal/v1/events/taxonomy"


def test_b2c_outbox_keeps_legacy_product_event_receiver(monkeypatch):
    requests = []

    class Response:
        status_code = 202

        def raise_for_status(self):
            return None

    class Client:
        def __init__(self, *, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, *, json, headers):
            requests.append(url)
            return Response()

    monkeypatch.setattr(b2c.httpx, "AsyncClient", Client)
    event = {"event_type": "PRODUCT_DELETED", "payload": {"product_id": "product"}}

    asyncio.run(b2c.B2CClient(base_url="http://b2c").send_outbox_event(event))

    assert requests == ["http://b2c/api/v1/b2b/events"]


def test_b2c_outbox_does_not_swallow_taxonomy_event_conflict(monkeypatch):
    class Response:
        status_code = 409

        def raise_for_status(self):
            raise httpx.HTTPStatusError(
                "conflicting event receipt",
                request=httpx.Request("POST", "http://b2c/internal/v1/events/taxonomy"),
                response=httpx.Response(409),
            )

    class Client:
        def __init__(self, *, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, *, json, headers):
            return Response()

    monkeypatch.setattr(b2c.httpx, "AsyncClient", Client)
    event = {
        "schema_version": 1,
        "event_type": "brand.merged.v1",
        "producer": "b2b",
        "aggregate_type": "brand",
    }

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(
            b2c.B2CClient(base_url="http://b2c").send_outbox_event(event)
        )
