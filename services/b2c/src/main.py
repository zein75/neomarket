from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator
import asyncio
import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.openapi.utils import get_openapi

from src.api.routers import addresses, auth, b2b_events, cart, catalog, favorites, health, home, orders
from src.core.database import AsyncSessionLocal
from src.core.config import settings
from src.services.order_service import OrderService
from shared.utils.request_id import RequestIdMiddleware
from shared.utils.metrics import MetricsMiddleware, render_metrics
from shared.utils.request_limits import RequestLimitsMiddleware


logger = logging.getLogger(__name__)


async def _retry_pending_cancellations(stop: asyncio.Event) -> None:
    """Retry durable cancellation intents; B2B unreserve is idempotent by order id."""
    while not stop.is_set():
        try:
            async with AsyncSessionLocal() as session:
                await OrderService(session).retry_pending_cancellations()
                await OrderService(session).retry_pending_reservation_compensations()
                await OrderService(session).retry_pending_fulfillments()
                await session.commit()
        except Exception:  # noqa: BLE001 - a later iteration must still run
            logger.exception("Failed to retry pending order cancellations")
        try:
            await asyncio.wait_for(
                stop.wait(), timeout=settings.recovery_worker_poll_interval_seconds
            )
        except TimeoutError:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    stop = asyncio.Event()
    retry_task = asyncio.create_task(_retry_pending_cancellations(stop))
    try:
        yield
    finally:
        stop.set()
        retry_task.cancel()
        await asyncio.gather(retry_task, return_exceptions=True)


app = FastAPI(
    title="NeoMarket B2C API",
    version="0.1.0",
    lifespan=lifespan,
)


def _openapi_with_security() -> dict[str, object]:
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
    schemes = schema.setdefault("components", {}).setdefault("securitySchemes", {})
    schemes.update({
        "userBearer": {"type": "http", "scheme": "bearer"},
        "serviceBearer": {"type": "http", "scheme": "bearer"},
        "mutualTLS": {"type": "mutualTLS"},
    })
    public_prefixes = (
        "/api/v1/catalog",
        "/api/v1/auth/login",
        "/api/v1/auth/refresh",
        "/api/v1/auth/reset-request",
        "/api/v1/auth/reset-confirm",
    )
    for path, operations in schema["paths"].items():
        for method, operation in operations.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            if path.startswith("/internal/v1/"):
                operation["security"] = [{"mutualTLS": [], "serviceBearer": []}]
            elif path.startswith("/api/v1/") and not path.startswith(public_prefixes):
                operation["security"] = [{"userBearer": []}]
            else:
                operation["security"] = []
    app.openapi_schema = schema
    return schema


app.openapi = _openapi_with_security
app.add_middleware(RequestIdMiddleware)
app.add_middleware(MetricsMiddleware)
app.add_middleware(RequestLimitsMiddleware)


@app.get("/metrics", include_in_schema=False)
async def metrics() -> PlainTextResponse:
    return PlainTextResponse(render_metrics(), media_type="text/plain; version=0.0.4")


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Keep public validation errors in the root-level Error envelope.

    FastAPI's default ``detail`` wrapper is not part of the B2C wire contract.
    Authentication dependencies still use their explicit 401 handler.
    """
    if settings.app_env.lower() in {"production", "prod"}:
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Request validation failed",
                    "details": {"errors": exc.errors()},
                    "retryable": False,
                },
                "request_id": getattr(request.state, "request_id", None),
            },
        )
    return JSONResponse(
        status_code=400,
        content={
            "code": "VALIDATION_ERROR",
            "message": "Request validation failed",
            "details": {
                "errors": [
                    {key: value for key, value in error.items() if key != "ctx"}
                    for error in exc.errors()
                ]
            },
        },
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    if settings.app_env.lower() in {"production", "prod"}:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        code = str(detail.get("code") or _error_code(exc.status_code))
        message = str(detail.get("message") or exc.detail)
        details = {k: v for k, v in detail.items() if k not in {"code", "message"}}
        headers = dict(exc.headers or {})
        if exc.status_code == 401:
            headers.setdefault("WWW-Authenticate", "Bearer")
        if exc.status_code in {429, 503}:
            headers.setdefault("Retry-After", "1")
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": code,
                    "message": message,
                    "details": details,
                    "retryable": exc.status_code in {429, 503},
                },
                "request_id": getattr(request.state, "request_id", None),
            },
            headers=headers,
        )
    if isinstance(exc.detail, dict) and {"code", "message"} <= set(exc.detail):
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    if isinstance(exc.detail, dict) and {"error", "message"} <= set(exc.detail):
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    if isinstance(exc.detail, dict) and {"is_valid", "cart", "issues"} <= set(exc.detail):
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": "HTTP_ERROR",
            "message": str(exc.detail),
        },
        headers=exc.headers,
    )


@app.exception_handler(Exception)
async def unexpected_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled B2C exception", exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "Internal server error",
                "details": {},
                "retryable": False,
            },
            "request_id": getattr(request.state, "request_id", None),
        },
    )


def _error_code(status_code: int) -> str:
    return {
        400: "INVALID_REQUEST",
        401: "AUTHENTICATION_REQUIRED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        409: "CONFLICT",
        422: "VALIDATION_ERROR",
        429: "RATE_LIMITED",
        503: "UPSTREAM_UNAVAILABLE",
    }.get(status_code, "INTERNAL_ERROR")


app.include_router(health.router)
app.include_router(auth.router)
app.include_router(addresses.router)
app.include_router(b2b_events.router)
app.include_router(cart.router)
app.include_router(favorites.router)
app.include_router(home.router)
app.include_router(orders.router)
app.include_router(catalog.router)
