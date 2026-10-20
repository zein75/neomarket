import hashlib
import json
import logging
import os
from contextvars import ContextVar
from time import perf_counter
from typing import Any
from uuid import UUID, uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


logger = logging.getLogger("neomarket.request")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _request_handler = logging.StreamHandler()
    _request_handler.setLevel(logging.INFO)
    _request_handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(_request_handler)
logger.propagate = False
request_id_context: ContextVar[str | None] = ContextVar("neomarket_request_id", default=None)


def _pseudonymous_actor_id(request: Request) -> str | None:
    actor = getattr(request.state, "actor_id", None) or getattr(request.state, "seller_id", None)
    if actor is None:
        return None
    service = os.getenv("NEOMARKET_SERVICE_NAME") or os.getenv("SERVICE_NAME", "service")
    return hashlib.sha256(f"{service}:{actor}".encode("utf-8")).hexdigest()[:16]


def request_log_payload(request: Request, response: Response, duration_ms: float) -> dict[str, Any]:
    """Build a bounded, PII-free JSON log record for one HTTP request."""
    route = request.scope.get("route")
    return {
        "event": "http_request",
        "service": os.getenv("NEOMARKET_SERVICE_NAME") or os.getenv("SERVICE_NAME", "service"),
        "deploy_sha": os.getenv("NEOMARKET_DEPLOY_SHA") or os.getenv("RELEASE_SHA", "unknown"),
        "request_id": getattr(request.state, "request_id", None),
        "trace_id": getattr(request.state, "request_id", None),
        "actor_id": _pseudonymous_actor_id(request),
        "method": request.method,
        "route": getattr(route, "path", "<unmatched>"),
        "status": response.status_code,
        "duration_ms": round(max(duration_ms, 0.0), 3),
    }


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Propagate a bounded request correlation identifier across HTTP hops."""

    async def dispatch(self, request: Request, call_next) -> Response:
        started = perf_counter()
        raw = request.headers.get("X-Request-ID")
        try:
            request_id = str(UUID(raw)) if raw else str(uuid4())
        except (ValueError, AttributeError):
            request_id = str(uuid4())
        request.state.request_id = request_id
        context_token = request_id_context.set(request_id)
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                json.dumps(
                    {
                        **request_log_payload(
                            request,
                            Response(status_code=500),
                            (perf_counter() - started) * 1000,
                        ),
                        "status": 500,
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
            raise
        finally:
            request_id_context.reset(context_token)
        response.headers["X-Request-ID"] = request_id
        logger.info(
            json.dumps(
                request_log_payload(request, response, (perf_counter() - started) * 1000),
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        return response
