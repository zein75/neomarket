from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from src.api.routers import (
    auth,
    categories,
    health,
    invoices,
    moderation_events,
    products,
    reservations,
    sellers,
    skus,
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    yield


app = FastAPI(
    title="NeoMarket B2B API",
    version="0.1.0",
    lifespan=lifespan,
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    if _missing_service_key_error(exc.errors()):
        return JSONResponse(
            status_code=401,
            content={
                "code": "SERVICE_KEY_INVALID",
                "message": "Invalid or missing service key",
            },
        )
    if request.method == "POST" and request.url.path == "/api/v1/products":
        return JSONResponse(
            status_code=400,
            content=_create_product_validation_error(exc.errors()),
        )
    return JSONResponse(
        status_code=400,
        content={
            "code": "VALIDATION_ERROR",
            "message": "Request validation failed",
            "errors": exc.errors(),
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
    if isinstance(exc.detail, dict) and {"code", "message"} <= set(exc.detail):
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
app.include_router(categories.router)
app.include_router(products.router)
app.include_router(skus.router)
app.include_router(invoices.router)
app.include_router(reservations.router)
app.include_router(moderation_events.router)
app.include_router(sellers.router)
