from http import HTTPStatus

from fastapi.responses import JSONResponse, Response
from fastapi import HTTPException
from starlette.requests import Request

from shared.utils.request_limits import RequestLimitsMiddleware
from src.core.config import settings
from src.services.rate_limiter import enforce_admin_rate_limit


class AdminRequestLimitsMiddleware(RequestLimitsMiddleware):
    """Keep early request-limit rejections inside Admin's Problem/security contract."""

    async def dispatch(self, request: Request, call_next) -> Response:
        response = None
        admin_api_path = request.url.path.startswith(("/admin/v1/", "/internal/v1/"))
        if admin_api_path:
            try:
                await enforce_admin_rate_limit(
                    client_ip=request.client.host if request.client else "unknown",
                    route=f"{request.method}:{request.url.path}",
                )
            except HTTPException as exc:
                detail = exc.detail if isinstance(exc.detail, dict) else {"code": "RATE_LIMITED", "message": str(exc.detail)}
                return self._problem(
                    request,
                    exc.status_code,
                    str(detail.get("code") or "RATE_LIMITED"),
                    str(detail.get("message") or "Request rate limit exceeded"),
                    headers=exc.headers,
                )
        if admin_api_path and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            chunks: list[bytes] = []
            total_bytes = 0
            async for chunk in request.stream():
                total_bytes += len(chunk)
                if total_bytes > self.max_body_bytes:
                    response = self._problem(request, 413, "REQUEST_TOO_LARGE", "Request body is too large")
                    break
                chunks.append(chunk)
            if response is None:
                body = b"".join(chunks)
                request._body = body
                content_type = request.headers.get("content-type", "").lower()
                if body and not content_type.startswith("application/json"):
                    response = self._problem(request, 415, "UNSUPPORTED_MEDIA_TYPE", "JSON content type is required")
        if response is None:
            response = await super().dispatch(request, call_next)
        if response.status_code in {413, 415}:
            status_code = response.status_code
            code = "REQUEST_TOO_LARGE" if status_code == 413 else "UNSUPPORTED_MEDIA_TYPE"
            detail = "Request body is too large" if status_code == 413 else "JSON content type is required"
            response = self._problem(request, status_code, code, detail)
        if request.url.path.startswith("/admin/v1/") or request.url.path == "/session":
            response.headers["Cache-Control"] = "private, no-store"
            response.headers["Pragma"] = "no-cache"
            response.headers["Vary"] = "Cookie"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if not settings.local_dev_auth_enabled:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
            response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
        return response

    @staticmethod
    def _problem(request: Request, status_code: int, code: str, detail: str, *, headers: dict[str, str] | None = None) -> JSONResponse:
        try:
            title = HTTPStatus(status_code).phrase
        except ValueError:
            title = "Request failed"
        return JSONResponse(
            status_code=status_code,
            media_type="application/problem+json",
            content={
                "type": f"urn:neomarket:problem:{code.lower()}",
                "title": title,
                "status": status_code,
                "detail": detail,
                "code": code,
                "instance": request.url.path,
                "request_id": getattr(request.state, "request_id", "unknown"),
                "retryable": status_code in {429, 503},
            },
            headers=headers,
        )
