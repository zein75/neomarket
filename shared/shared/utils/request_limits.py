from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


class RequestLimitsMiddleware(BaseHTTPMiddleware):
    """Reject oversized or non-JSON mutation requests before parsing the body."""

    max_body_bytes = 256 * 1024
    max_media_upload_bytes = 10_000_000

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.method in {"POST", "PUT", "PATCH"}:
            media_upload = (
                request.method == "PUT"
                and request.url.path.startswith("/api/v1/media/uploads/")
            )
            if media_upload:
                raw_length = request.headers.get("content-length")
                try:
                    content_length = int(raw_length) if raw_length is not None else 0
                except ValueError:
                    content_length = self.max_media_upload_bytes + 1
                if content_length < 1 or content_length > self.max_media_upload_bytes:
                    return JSONResponse(status_code=413, content={"code": "MEDIA_TOO_LARGE", "message": "Image exceeds the 10 MB limit"})
                content_type = request.headers.get("content-type", "").lower().split(";", 1)[0].strip()
                if content_type not in {"image/jpeg", "image/png", "image/webp"}:
                    return JSONResponse(status_code=415, content={"code": "UNSUPPORTED_MEDIA_TYPE", "message": "Only JPEG, PNG and WebP uploads are accepted"})
                return await call_next(request)
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
            form_login = (
                request.url.path in {"/auth/login", "/api/v1/auth/login"}
                and content_type.startswith("application/x-www-form-urlencoded")
            )
            if content_length and not content_type.startswith("application/json") and not form_login:
                return JSONResponse(
                    status_code=415,
                    content={
                        "code": "UNSUPPORTED_MEDIA_TYPE",
                        "message": "JSON content type is required",
                    },
                )
        return await call_next(request)
