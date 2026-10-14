from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


class RequestLimitsMiddleware(BaseHTTPMiddleware):
    """Reject oversized or non-JSON mutation requests before parsing the body."""

    max_body_bytes = 256 * 1024

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.method in {"POST", "PUT", "PATCH"}:
            raw_length = request.headers.get("content-length")
            try:
                content_length = int(raw_length) if raw_length is not None else 0
            except ValueError:
                content_length = self.max_body_bytes + 1
            if content_length > self.max_body_bytes:
                return JSONResponse(
                    status_code=413,
                    content={
                        "code": "REQUEST_TOO_LARGE",
                        "message": "Request body is too large",
                    },
                )
            content_type = request.headers.get("content-type", "").lower()
            if content_length and not content_type.startswith("application/json"):
                return JSONResponse(
                    status_code=415,
                    content={
                        "code": "UNSUPPORTED_MEDIA_TYPE",
                        "message": "JSON content type is required",
                    },
                )
        return await call_next(request)
