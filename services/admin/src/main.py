import asyncio
import logging
from collections.abc import AsyncGenerator

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.openapi.utils import get_openapi
from sqlalchemy import text

from src.core.database import AsyncSessionLocal
from src.core.config import settings
from src.services.moderation_service import ModerationService

from src.api.routers import moderation
from shared.utils.request_id import RequestIdMiddleware
from shared.utils.metrics import MetricsMiddleware, record_worker_metric, render_metrics
from shared.utils.request_limits import RequestLimitsMiddleware


logger = logging.getLogger(__name__)


async def _moderation_outbox_worker(stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            record_worker_metric("admin_moderation_outbox", "iterations")
            async with AsyncSessionLocal() as session:
                delivered = await ModerationService(session).retry_pending_decisions()
                record_worker_metric("admin_moderation_outbox", "delivered", delivered)
                await session.commit()
        except Exception:  # noqa: BLE001 - worker must survive transient DB/B2B failures
            record_worker_metric("admin_moderation_outbox", "failures")
        try:
            await asyncio.wait_for(
                stop.wait(), timeout=settings.moderation_outbox_poll_interval_seconds
            )
        except TimeoutError:
            continue


async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    stop = asyncio.Event()
    worker = asyncio.create_task(_moderation_outbox_worker(stop))
    try:
        yield
    finally:
        stop.set()
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


app = FastAPI(title="NeoMarket Moderation API", version="0.1.0", lifespan=lifespan)


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
    for path, operations in schema["paths"].items():
        for method, operation in operations.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            if path.startswith("/admin/v1/"):
                operation["security"] = [{"userBearer": []}]
            elif path.startswith("/internal/v1/"):
                operation["security"] = [{"mutualTLS": [], "serviceBearer": []}]
    app.openapi_schema = schema
    return schema


app.openapi = _openapi_with_security
app.add_middleware(RequestIdMiddleware)
app.add_middleware(MetricsMiddleware)
app.add_middleware(RequestLimitsMiddleware)


@app.get("/metrics", include_in_schema=False)
async def metrics() -> PlainTextResponse:
    return PlainTextResponse(render_metrics(), media_type="text/plain; version=0.0.4")


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/live", tags=["health"])
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready", tags=["health"])
async def readiness() -> dict[str, str]:
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - readiness must fail closed
        raise HTTPException(
            status_code=503,
            detail={"code": "NOT_READY", "message": "Database unavailable"},
        ) from exc
    return {"status": "ok"}


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    if settings.app_env.lower() in {"production", "prod"}:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        headers = dict(exc.headers or {})
        if exc.status_code == 401:
            headers.setdefault("WWW-Authenticate", "Bearer")
        if exc.status_code in {429, 503}:
            headers.setdefault("Retry-After", "1")
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": str(detail.get("code") or _default_error_code(exc.status_code)),
                    "message": str(detail.get("message") or exc.detail),
                    "details": {k: v for k, v in detail.items() if k not in {"code", "message"}},
                    "retryable": exc.status_code in {429, 503},
                },
                "request_id": getattr(request.state, "request_id", None),
            },
            headers=headers,
        )
    if isinstance(exc.detail, dict):
        content = dict(exc.detail)
        content.setdefault("code", _default_error_code(exc.status_code))
        content.setdefault("message", _default_error_message(exc.status_code))
        return JSONResponse(
            status_code=exc.status_code,
            content=content,
            headers=exc.headers,
        )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": _default_error_code(exc.status_code),
            "message": str(exc.detail),
        },
        headers=exc.headers,
    )


@app.exception_handler(Exception)
async def unexpected_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled Admin exception", exc_info=exc)
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


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    if settings.app_env.lower() in {"production", "prod"}:
        return JSONResponse(
            status_code=422,
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
        status_code=422,
        content={
            "code": "VALIDATION_ERROR",
            "message": "Request validation failed",
            "details": exc.errors(),
        },
    )


def _default_error_code(status_code: int) -> str:
    return {
        400: "INVALID_REQUEST",
        401: "UNAUTHORIZED",
        404: "NOT_FOUND",
        409: "CONFLICT",
        503: "SERVICE_UNAVAILABLE",
    }.get(status_code, "HTTP_ERROR")


def _default_error_message(status_code: int) -> str:
    return {
        400: "Invalid request",
        401: "Unauthorized",
        404: "Resource not found",
        409: "Conflict",
        503: "Service unavailable",
    }.get(status_code, "Request failed")


app.include_router(moderation.router)
