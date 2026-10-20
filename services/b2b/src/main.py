import asyncio
import logging
import os
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.openapi.utils import get_openapi

from src.api.routers import (
    auth,
    admin_internal,
    categories,
    finance,
    health,
    invoices,
    moderation_events,
    products,
    reservations,
    sellers,
    seller_orders,
    seller_inventory,
    seller_media,
    skus,
    team,
)
from src.core.database import AsyncSessionLocal
from src.core.config import settings
from src.services.reservation_service import ReservationService
from src.services.seller_media_service import SellerMediaService
from src.services.inventory_export_service import InventoryExportService, delete_artifact
from shared.utils.request_id import RequestIdMiddleware
from shared.utils.metrics import MetricsMiddleware, record_worker_metric, render_metrics
from shared.utils.request_limits import RequestLimitsMiddleware


logger = logging.getLogger(__name__)
logging.getLogger().setLevel(os.getenv("LOG_LEVEL", "INFO").upper())


async def _outbox_worker() -> None:
    while True:
        try:
            record_worker_metric("b2b_outbox", "iterations")
            async with AsyncSessionLocal() as session:
                delivered = await ReservationService(session).retry_pending_outbox()
                record_worker_metric("b2b_outbox", "delivered", delivered)
                await session.commit()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - worker must survive transient failures
            record_worker_metric("b2b_outbox", "failures")
            logger.exception("B2B outbox worker iteration failed")
        await asyncio.sleep(settings.outbox_poll_interval_seconds)


async def _media_scan_worker() -> None:
    while True:
        try:
            record_worker_metric("b2b_media_scan", "iterations")
            async with AsyncSessionLocal() as session:
                scanned = await SellerMediaService.scan_once(session)
                if scanned:
                    record_worker_metric("b2b_media_scan", "processed")
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - scanner outages must not stop the API
            record_worker_metric("b2b_media_scan", "failures")
            logger.exception("B2B media scanner iteration failed")
        await asyncio.sleep(settings.media_scan_poll_interval_seconds)


async def _inventory_export_worker() -> None:
    while True:
        try:
            record_worker_metric("b2b_inventory_export", "iterations")
            async with AsyncSessionLocal() as session:
                now = datetime.now(timezone.utc)
                expired = await InventoryExportService.expire_ready(session, now)
                terminal = await InventoryExportService.cleanup_terminal(session, now)
                claim = await InventoryExportService.claim_next(session, now)
                for seller_id, expired_job_id in (*expired, *terminal):
                    delete_artifact(seller_id, expired_job_id)
                await session.commit()
            if claim:
                job_id, lease_generation = claim
                await InventoryExportService.process(job_id, lease_generation, AsyncSessionLocal)
                record_worker_metric("b2b_inventory_export", "processed")
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - export worker must survive transient failures
            record_worker_metric("b2b_inventory_export", "failures")
            logger.exception("B2B inventory export worker iteration failed")
        await asyncio.sleep(settings.inventory_export_poll_interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    worker = asyncio.create_task(_outbox_worker())
    media_worker = asyncio.create_task(_media_scan_worker())
    inventory_export_worker = asyncio.create_task(_inventory_export_worker())
    yield
    worker.cancel()
    media_worker.cancel()
    inventory_export_worker.cancel()
    await asyncio.gather(worker, media_worker, inventory_export_worker, return_exceptions=True)


app = FastAPI(
    title="NeoMarket B2B API",
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
        "serviceJWT": {"type": "http", "scheme": "bearer"},
        "mutualTLS": {"type": "mutualTLS"},
    })
    for path, operations in schema["paths"].items():
        for method, operation in operations.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            if path.startswith("/api/v1/seller/"):
                operation["security"] = [{"userBearer": []}]
            elif path == "/internal/v1/moderation/decisions":
                operation["security"] = [{"serviceJWT": []}]
            elif path.startswith("/internal/v1/taxonomy/"):
                operation["security"] = [{"serviceJWT": []}]
            elif path.startswith("/internal/v1/"):
                operation["security"] = [{"mutualTLS": [], "serviceBearer": []}]
    app.openapi_schema = schema
    return schema


app.openapi = _openapi_with_security
app.add_middleware(RequestIdMiddleware)
app.add_middleware(MetricsMiddleware)
app.add_middleware(RequestLimitsMiddleware)


@app.middleware("http")
async def finance_no_store(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith(
        ("/api/v1/seller/finance/", "/finance/")
    ):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/metrics", include_in_schema=False)
async def metrics() -> PlainTextResponse:
    return PlainTextResponse(render_metrics(), media_type="text/plain; version=0.0.4")


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    if settings.app_env.lower() in {"production", "prod"}:
        return JSONResponse(
            status_code=422,
            content={
                "error": {"code": "VALIDATION_ERROR", "message": "Request validation failed", "details": {"errors": exc.errors()}, "retryable": False},
                "request_id": getattr(request.state, "request_id", None),
            },
        )
    errors = [
        {key: value for key, value in error.items() if key != "ctx"}
        for error in exc.errors()
    ]
    if _missing_service_key_error(errors):
        return JSONResponse(
            status_code=401,
            content={
                "code": "SERVICE_KEY_INVALID",
                "message": "Invalid or missing service key",
            },
        )
    if request.method == "POST" and request.url.path == "/seller/v1/products/drafts":
        return JSONResponse(
            status_code=422,
            content={
                "code": "VALIDATION_ERROR",
                "message": "Request validation failed",
                "errors": errors,
            },
        )
    if request.method == "POST" and request.url.path == "/api/v1/products":
        return JSONResponse(
            status_code=400,
            content=_create_product_validation_error(errors),
        )
    return JSONResponse(
        status_code=400,
        content={
            "code": "VALIDATION_ERROR",
            "message": "Request validation failed",
            "errors": errors,
        },
    )


def _missing_service_key_error(errors: list[dict[str, object]]) -> bool:
    for error in errors:
        location = [str(part).lower() for part in error.get("loc") or []]
        if location == ["header", "x-service-key"]:
            return True
    return False


def _create_product_validation_error(errors: list[dict[str, object]]) -> dict[str, str]:
    for error in errors:
        location = list(error.get("loc") or [])
        field = location[-1] if location else None
        error_type = str(error.get("type", ""))
        if field == "images":
            return {
                "code": "INVALID_REQUEST",
                "message": "At least one image is required",
            }
        if field == "category_id":
            if "uuid" in error_type or "parsing" in error_type:
                return {
                    "code": "INVALID_REQUEST",
                    "message": "category_id must be a valid UUID",
                }
            return {
                "code": "INVALID_REQUEST",
                "message": "category_id is required",
            }
        if field == "title":
            if "missing" in error_type or "too_short" in error_type:
                return {"code": "INVALID_REQUEST", "message": "title is required"}
            return {
                "code": "INVALID_REQUEST",
                "message": "title must be 1-255 characters",
            }
        if field == "description":
            return {"code": "INVALID_REQUEST", "message": "description is required"}
    return {"code": "INVALID_REQUEST", "message": "Invalid request"}


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
                    "code": str(detail.get("code") or "HTTP_ERROR"),
                    "message": str(detail.get("message") or exc.detail),
                    "details": {k: v for k, v in detail.items() if k not in {"code", "message"}},
                    "retryable": exc.status_code in {429, 503},
                },
                "request_id": getattr(request.state, "request_id", None),
            },
            headers=headers,
        )
    if isinstance(exc.detail, dict) and {"code", "message"} <= set(exc.detail):
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.detail,
            headers=exc.headers,
        )
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
    logger.exception("Unhandled B2B exception", exc_info=exc)
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


app.include_router(health.router)
app.include_router(auth.router)
app.include_router(admin_internal.router)
app.include_router(categories.router)
app.include_router(finance.router)
app.include_router(products.router)
app.include_router(skus.router)
app.include_router(invoices.router)
app.include_router(reservations.router)
app.include_router(moderation_events.router)
app.include_router(sellers.router)
app.include_router(seller_orders.router)
app.include_router(seller_inventory.router)
app.include_router(seller_media.router)
app.include_router(team.router)
