from uuid import UUID, uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Propagate a bounded request correlation identifier across HTTP hops."""

    async def dispatch(self, request: Request, call_next) -> Response:
        raw = request.headers.get("X-Request-ID")
        try:
            request_id = str(UUID(raw)) if raw else str(uuid4())
        except (ValueError, AttributeError):
            request_id = str(uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
