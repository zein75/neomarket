from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator
import asyncio
import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from src.api.routers import auth, b2b_events, cart, catalog, favorites, health, home, orders
from src.core.database import AsyncSessionLocal
from src.services.order_service import OrderService


logger = logging.getLogger(__name__)


async def _retry_pending_cancellations(stop: asyncio.Event) -> None:
    """Retry durable cancellation intents; B2B unreserve is idempotent by order id."""
    while not stop.is_set():
        try:
            async with AsyncSessionLocal() as session:
                await OrderService(session).retry_pending_cancellations()
                await OrderService(session).retry_pending_reservation_compensations()
                await session.commit()
        except Exception:  # noqa: BLE001 - a later iteration must still run
            logger.exception("Failed to retry pending order cancellations")
        try:
            await asyncio.wait_for(stop.wait(), timeout=30)
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
        await retry_task


app = FastAPI(
    title="NeoMarket B2C API",
    version="0.1.0",
    lifespan=lifespan,
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Keep public validation errors in the root-level Error envelope.

    FastAPI's default ``detail`` wrapper is not part of the B2C wire contract.
    Authentication dependencies still use their explicit 401 handler.
    """
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


app.include_router(health.router)
app.include_router(auth.router)
app.include_router(b2b_events.router)
app.include_router(cart.router)
app.include_router(favorites.router)
app.include_router(home.router)
app.include_router(orders.router)
app.include_router(catalog.router)
