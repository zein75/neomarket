from types import SimpleNamespace

from starlette.requests import Request
from starlette.responses import Response
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from shared.utils.request_id import RequestIdMiddleware, logger, request_log_payload


def test_request_id_middleware_is_available():
    assert RequestIdMiddleware is not None


def test_request_log_payload_is_bounded_and_pseudonymous(monkeypatch):
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/seller/products/secret-id",
            "headers": [],
            "query_string": b"seller_email=private@example.invalid",
            "scheme": "http",
            "server": ("test", 80),
            "client": ("127.0.0.1", 1234),
            "root_path": "",
        }
    )
    request.scope["route"] = SimpleNamespace(path="/api/v1/seller/products/{product_id}")
    request.state.request_id = "b0fc9499-0ef9-4f54-85a2-3ae32cb1f954"
    request.state.seller_id = "seller-private-id"
    monkeypatch.setenv("NEOMARKET_SERVICE_NAME", "b2b")
    monkeypatch.setenv("NEOMARKET_DEPLOY_SHA", "sha-test")

    payload = request_log_payload(request, Response(status_code=200), 1.23456)

    assert payload == {
        "event": "http_request",
        "service": "b2b",
        "deploy_sha": "sha-test",
        "request_id": "b0fc9499-0ef9-4f54-85a2-3ae32cb1f954",
        "trace_id": "b0fc9499-0ef9-4f54-85a2-3ae32cb1f954",
        "actor_id": "53b7380dfb132cc1",
        "method": "GET",
        "route": "/api/v1/seller/products/{product_id}",
        "status": 200,
        "duration_ms": 1.235,
    }
    assert "secret-id" not in str(payload)
    assert "private@example.invalid" not in str(payload)


def test_request_id_middleware_emits_correlated_json_log(caplog, monkeypatch):
    async def endpoint(request):
        request.state.seller_id = "seller-id"
        return Response("ok")

    app = Starlette(routes=[Route("/products/{product_id}", endpoint)])
    app.add_middleware(RequestIdMiddleware)
    monkeypatch.setenv("SERVICE_NAME", "b2b")
    monkeypatch.setenv("RELEASE_SHA", "sha-test")
    monkeypatch.setattr(logger, "propagate", True)
    request_id = "c432f50d-a1cc-43c5-9079-9582f71181f5"

    with caplog.at_level("INFO", logger="neomarket.request"):
        response = TestClient(app).get("/products/secret-id", headers={"X-Request-ID": request_id})

    assert response.headers["X-Request-ID"] == request_id
    records = [record for record in caplog.records if record.name == "neomarket.request"]
    assert len(records) == 1
    log_output = records[0].getMessage()
    assert log_output.startswith('{')
    assert '"request_id":"c432f50d-a1cc-43c5-9079-9582f71181f5"' in log_output
    assert '"route":"/products/{product_id}"' in log_output
    assert "secret-id" not in log_output
