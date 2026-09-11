from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from src.api.routers import moderation


app = FastAPI(title="NeoMarket Moderation API", version="0.1.0")


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
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


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
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
