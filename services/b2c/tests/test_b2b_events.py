from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient

from src.main import app


def _event(**overrides: object) -> dict[str, object]:
    event: dict[str, object] = {
        "event_type": "SKU_OUT_OF_STOCK",
        "idempotency_key": str(uuid4()),
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "payload": {"sku_id": str(uuid4())},
    }
    event.update(overrides)
    return event


def test_receive_sku_out_of_stock_event_returns_204() -> None:
    response = TestClient(app).post(
        "/api/v1/b2b/events",
        headers={"X-Service-Key": "dev-service-key-change-in-production"},
        json=_event(),
    )

    assert response.status_code == 204
    assert response.content == b""


def test_receive_b2b_event_without_service_key_returns_401() -> None:
    response = TestClient(app).post("/api/v1/b2b/events", json=_event())

    assert response.status_code == 401
    assert response.json() == {
        "code": "SERVICE_KEY_INVALID",
        "message": "Invalid or missing service key",
    }
