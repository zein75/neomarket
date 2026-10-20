import asyncio

from src.clients import moderation


def test_publication_result_is_sent_as_the_canonical_admin_event(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

    class FakeHTTPClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            return None

        async def post(self, url: str, *, json: dict[str, object], headers: dict[str, str]):
            calls.append({"url": url, "json": json, "headers": headers})
            return FakeResponse()

    monkeypatch.setattr(moderation.httpx, "AsyncClient", lambda **_: FakeHTTPClient())
    envelope = {
        "schema_version": 1,
        "event_id": "48250e3a-91a8-53b8-8c84-dbed3d357041",
        "event_type": "product.publication.applied.v1",
        "producer": "b2b",
        "aggregate_type": "product",
        "aggregate_id": "6f465836-b34a-4cfe-86d1-c5c846dc12a7",
        "aggregate_version": 4,
        "occurred_at": "2026-10-18T16:00:00Z",
        "correlation_id": "024fc24e-aaf1-4e50-8333-a6594cd0c17e",
        "causation_id": "28a2cce6-f465-4678-bf95-c4160a001f3f",
        "payload": {
            "decision_id": "28a2cce6-f465-4678-bf95-c4160a001f3f",
            "product_id": "6f465836-b34a-4cfe-86d1-c5c846dc12a7",
            "submitted_revision": 4,
            "action": "APPROVE",
            "published_revision": 4,
            "visible": True,
            "reason_code": None,
        },
    }

    client = moderation.ModerationClient(base_url="http://admin.local", service_key="test-service-key")
    asyncio.run(client._post_event(envelope))

    assert len(calls) == 1
    assert calls[0]["url"] == "http://admin.local/internal/v1/events/products"
    assert calls[0]["json"] == envelope
    assert calls[0]["headers"]["X-Service-Key"] == "test-service-key"
