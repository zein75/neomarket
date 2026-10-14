from collections import Counter

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


_REQUESTS: Counter[tuple[str, str, int]] = Counter()
_WORKER_EVENTS: Counter[tuple[str, str]] = Counter()


def record_worker_metric(worker: str, metric: str, value: int = 1) -> None:
    """Record bounded worker counters for operational dashboards."""
    if value > 0:
        _WORKER_EVENTS[(worker, metric)] += value


class MetricsMiddleware(BaseHTTPMiddleware):
    """Small in-process Prometheus counter with bounded route labels."""

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        route = request.scope.get("route")
        # Unmatched routes must not put arbitrary URLs/UUIDs into metric labels.
        path = getattr(route, "path", "<unmatched>")
        _REQUESTS[(request.method, path, response.status_code)] += 1
        return response


def render_metrics() -> str:
    lines = [
        "# HELP http_requests_total Total HTTP requests by method, route and status.",
        "# TYPE http_requests_total counter",
    ]
    for (method, route, status), count in sorted(_REQUESTS.items()):
        labels = f'method="{method}",route="{route}",status="{status}"'
        lines.append(f"http_requests_total{{{labels}}} {count}")
    lines.extend(
        [
            "# HELP worker_events_total Background worker counters.",
            "# TYPE worker_events_total counter",
        ]
    )
    for (worker, metric), count in sorted(_WORKER_EVENTS.items()):
        labels = f'worker="{worker}",event="{metric}"'
        lines.append(f"worker_events_total{{{labels}}} {count}")
    return "\n".join(lines) + "\n"
