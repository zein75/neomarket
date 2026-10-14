from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.utils.request_limits import RequestLimitsMiddleware


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestLimitsMiddleware)

    @app.post("/write")
    async def write(payload: dict[str, object]) -> dict[str, object]:
        return payload

    return app


def test_rejects_non_json_mutation() -> None:
    response = TestClient(_app()).post("/write", content="x", headers={"content-type": "text/plain"})
    assert response.status_code == 415
    assert response.json()["code"] == "UNSUPPORTED_MEDIA_TYPE"


def test_rejects_oversized_mutation() -> None:
    response = TestClient(_app()).post(
        "/write",
        content=b"x" * (RequestLimitsMiddleware.max_body_bytes + 1),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 413
    assert response.json()["code"] == "REQUEST_TOO_LARGE"
