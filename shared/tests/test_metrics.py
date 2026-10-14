from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.utils.metrics import MetricsMiddleware, render_metrics


def test_metrics_do_not_use_unmatched_url_as_label():
    app = FastAPI()
    app.add_middleware(MetricsMiddleware)
    client = TestClient(app)
    client.get("/missing/123e4567-e89b-12d3-a456-426614174000")

    metrics = render_metrics()
    assert '<unmatched>' in metrics
    assert "123e4567-e89b-12d3-a456-426614174000" not in metrics
