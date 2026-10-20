import asyncio
import logging
from collections.abc import AsyncGenerator
from http import HTTPStatus
from pathlib import Path

from alembic.script import ScriptDirectory
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.openapi.utils import get_openapi
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from src.core.database import AsyncSessionLocal
from src.core.config import settings
from src.services.operational_metrics import render_operational_metrics
from src.workers.outbox import moderation_outbox_worker

from src.api.routers import appeals, audit_exports, bulk_operations, complaints, iam, integrations, moderation, operations, policies, policy_reasons, products, sellers, sessions, taxonomy
from shared.utils.request_id import RequestIdMiddleware
from shared.utils.metrics import MetricsMiddleware, render_metrics
from src.api.middleware import AdminRequestLimitsMiddleware


logger = logging.getLogger(__name__)
_ADMIN_MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"
_ADMIN_SCHEMA_HEADS = frozenset(ScriptDirectory(str(_ADMIN_MIGRATIONS)).get_heads())


def _remove_nullable_branches(value: object) -> object:
    if isinstance(value, list):
        return [_remove_nullable_branches(item) for item in value]
    if not isinstance(value, dict):
        return value
    normalized = {key: _remove_nullable_branches(item) for key, item in value.items()}
    branches = normalized.get("anyOf")
    if isinstance(branches, list):
        non_null = [branch for branch in branches if branch != {"type": "null"}]
        if len(non_null) == 1:
            metadata = {key: item for key, item in normalized.items() if key not in {"anyOf", "default"}}
            normalized = {**non_null[0], **metadata}
        elif len(non_null) != len(branches):
            normalized["anyOf"] = non_null
    if normalized.get("default", object()) is None:
        normalized.pop("default", None)
    return normalized


async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    stop = asyncio.Event()
    worker = (
        asyncio.create_task(moderation_outbox_worker(stop))
        if settings.admin_run_outbox_worker
        else None
    )
    try:
        yield
    finally:
        if worker is not None:
            stop.set()
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)


deployed_environment = not settings.local_dev_auth_enabled
app = FastAPI(
    title="NeoMarket Admin API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None if deployed_environment else "/docs",
    redoc_url=None if deployed_environment else "/redoc",
    openapi_url=None if deployed_environment else "/openapi.json",
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.admin_public_origin.rstrip("/")] if settings.admin_public_origin else [],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-CSRF-Token", "Idempotency-Key", "If-Match", "X-Request-ID", "Sec-Fetch-Site"],
    expose_headers=["ETag", "X-Request-ID", "Retry-After", "Content-Disposition"],
    max_age=600,
)


def _openapi_with_security() -> dict[str, object]:
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
    decision_input = schema.get("components", {}).get("schemas", {}).get("DecisionInput")
    if isinstance(decision_input, dict):
        decision_input.get("properties", {}).get("passed_rules", {})["description"] = (
            "Rule codes the moderator recorded as passed for an approval."
        )
        decision_input["allOf"] = [
            {
                "if": {"properties": {"action": {"const": "CHANGES_REQUESTED"}}, "required": ["action"]},
                "then": {"properties": {"field_reports": {"minItems": 1}}},
            },
            {
                "if": {
                    "properties": {"action": {"enum": ["REJECT", "HARD_BLOCK"]}},
                    "required": ["action"],
                },
                "then": {
                    "properties": {"field_reports": {"minItems": 1}, "comment": {"minLength": 1}},
                },
            },
            {
                "if": {"properties": {"action": {"const": "APPROVE"}}, "required": ["action"]},
                "then": {"properties": {"passed_rules": {"minItems": 1}}},
            },
            {
                "if": {
                    "properties": {
                        "action": {"enum": ["CHANGES_REQUESTED", "REJECT", "HARD_BLOCK", "ESCALATE"]},
                    },
                    "required": ["action"],
                },
                "then": {"properties": {"passed_rules": {"maxItems": 0}}},
            },
        ]
    schemes = schema.setdefault("components", {}).setdefault("securitySchemes", {})
    schemes.update({
        "adminSession": {"type": "apiKey", "in": "cookie", "name": "__Host-nm_admin_access"},
        "oidcBearer": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"},
        "serviceBearer": {"type": "http", "scheme": "bearer"},
        "mutualTLS": {"type": "mutualTLS"},
    })
    schema.setdefault("components", {}).setdefault("schemas", {})["Problem"] = {
        "type": "object",
        "properties": {
            "type": {"type": "string"},
            "title": {"type": "string"},
            "status": {"type": "integer"},
            "detail": {"type": "string"},
            "code": {"type": "string"},
            "instance": {"type": "string"},
            "request_id": {"type": "string"},
            "retryable": {"type": "boolean"},
            "errors": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"field": {"type": "string"}, "message": {"type": "string"}},
                    "required": [],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["type", "title", "status", "code", "request_id", "retryable"],
        "additionalProperties": False,
    }
    problem_content = {"application/problem+json": {"schema": {"$ref": "#/components/schemas/Problem"}}}
    route_metadata = {
        (route.path, method.lower()): route
        for route in app.routes
        if getattr(route, "methods", None)
        for method in route.methods
    }
    for path, path_operations in schema["paths"].items():
        for method, operation in path_operations.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            if path.startswith("/admin/v1/"):
                if path == "/admin/v1/auth/session":
                    operation["security"] = [{"oidcBearer": []}]
                elif path == "/admin/v1/auth/step-up":
                    operation["security"] = [{"oidcBearer": [], "adminSession": []}]
                else:
                    operation["security"] = [{"adminSession": []}]
                segments = [part.strip("{}").replace("-", "_") for part in path.strip("/").split("/")]
                operation["operationId"] = f"{method.upper()}_{'_'.join(segments)}"
                route = route_metadata.get((path, method))
                if route is not None:
                    pending = list(route.dependant.dependencies)
                    while pending:
                        dependency = pending.pop()
                        permission = getattr(dependency.call, "required_permission", None)
                        if permission:
                            operation["x-required-permission"] = permission
                        pending.extend(dependency.dependencies)
                if path == "/admin/v1/operations/{operation_id}/approve":
                    operation["x-required-permission"] = "operations.approve"
                for status_code, description in {
                    "401": "Unauthenticated",
                    "403": "Permission denied",
                    "409": "State or idempotency conflict",
                    "412": "Version precondition failed",
                    "422": "Validation failed",
                    "429": "Rate limited",
                    "503": "Dependency unavailable",
                }.items():
                    error_response = operation["responses"].setdefault(status_code, {"description": description})
                    error_response["content"] = problem_content
            elif path.startswith("/internal/v1/"):
                operation["security"] = [{"mutualTLS": [], "serviceBearer": []}]
    schema = _remove_nullable_branches(schema)
    app.openapi_schema = schema
    return schema


app.openapi = _openapi_with_security
app.add_middleware(RequestIdMiddleware)
app.add_middleware(MetricsMiddleware)
app.add_middleware(AdminRequestLimitsMiddleware)


@app.get("/metrics", include_in_schema=False)
async def metrics() -> PlainTextResponse:
    try:
        async with AsyncSessionLocal() as session:
            operational = await render_operational_metrics(session)
    except Exception as exc:  # noqa: BLE001 - monitoring must expose DB metric failures
        logger.error("Admin operational metrics collection failed (%s)", type(exc).__name__)
        return PlainTextResponse(
            render_metrics()
            + "# HELP admin_metrics_collection_error Whether queue metrics could be collected.\n"
            + "# TYPE admin_metrics_collection_error gauge\n"
            + "admin_metrics_collection_error 1\n",
            status_code=503,
            media_type="text/plain; version=0.0.4",
        )
    operational += (
        "# HELP admin_metrics_collection_error Whether queue metrics could be collected.\n"
        "# TYPE admin_metrics_collection_error gauge\n"
        "admin_metrics_collection_error 0\n"
    )
    return PlainTextResponse(render_metrics() + operational, media_type="text/plain; version=0.0.4")


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
            if deployed_environment:
                applied_heads = frozenset((await session.scalars(text("SELECT version_num FROM alembic_version"))).all())
                if applied_heads != _ADMIN_SCHEMA_HEADS:
                    raise RuntimeError("Admin database migrations do not match this application revision")
                role = (await session.execute(text("""
                    SELECT rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls, rolinherit,
                           has_table_privilege(current_user,'audit_logs','UPDATE') AS audit_update,
                           has_table_privilege(current_user,'audit_logs','DELETE') AS audit_delete,
                           has_table_privilege(current_user,'audit_logs','TRUNCATE') AS audit_truncate
                      FROM pg_roles WHERE rolname = current_user
                """))).mappings().one_or_none()
                if (
                    role is None
                    or not role["rolcanlogin"]
                    or role["rolsuper"]
                    or role["rolcreatedb"]
                    or role["rolcreaterole"]
                    or role["rolreplication"]
                    or role["rolbypassrls"]
                    or role["rolinherit"]
                    or role["audit_update"]
                    or role["audit_delete"]
                    or role["audit_truncate"]
                ):
                    raise RuntimeError("Admin runtime database role must be non-superuser and append-only for audit_logs")
    except Exception as exc:  # noqa: BLE001 - readiness must fail closed
        # Keep the response generic for clients, but record the non-secret
        # failure class/message so staging diagnostics can identify whether a
        # migration-head or runtime-role check is blocking readiness.
        logger.error("Admin readiness check failed (%s): %s", type(exc).__name__, exc)
        raise HTTPException(
            status_code=503,
            detail={"code": "NOT_READY", "message": "Database unavailable or schema is not current"},
        ) from exc
    return {"status": "ok"}


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, dict) else {}
    headers = dict(exc.headers or {})
    if exc.status_code in {429, 503}:
        headers.setdefault("Retry-After", "1")
    code = str(detail.get("code") or _default_error_code(exc.status_code))
    message = str(detail.get("message") or (exc.detail if isinstance(exc.detail, str) else _default_error_message(exc.status_code)))
    return _problem_response(
        request,
        status_code=exc.status_code,
        code=code,
        detail=message,
        headers=headers,
    )


@app.exception_handler(Exception)
async def unexpected_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled Admin exception", exc_info=exc)
    return _problem_response(request, status_code=500, code="INTERNAL_ERROR", detail="Internal server error")


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    errors = [
        {"field": ".".join(str(part) for part in item.get("loc", ())), "message": str(item.get("msg", "Invalid value"))}
        for item in exc.errors()
    ]
    return _problem_response(
        request,
        status_code=422,
        code="VALIDATION_ERROR",
        detail="Request validation failed",
        errors=errors,
    )


def _problem_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    detail: str,
    errors: list[dict[str, str]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    try:
        title = HTTPStatus(status_code).phrase
    except ValueError:
        title = "Request failed"
    content: dict[str, object] = {
        "type": f"urn:neomarket:problem:{code.lower()}",
        "title": title,
        "status": status_code,
        "detail": detail,
        "code": code,
        "instance": request.url.path,
        "request_id": getattr(request.state, "request_id", "unknown"),
        "retryable": status_code in {429, 503, 500},
    }
    if errors:
        content["errors"] = errors
    return JSONResponse(
        status_code=status_code,
        content=content,
        headers=headers,
        media_type="application/problem+json",
    )


def _default_error_code(status_code: int) -> str:
    return {
        400: "INVALID_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        409: "CONFLICT",
        412: "PRECONDITION_FAILED",
        422: "VALIDATION_ERROR",
        429: "RATE_LIMITED",
        500: "INTERNAL_ERROR",
        503: "SERVICE_UNAVAILABLE",
    }.get(status_code, "HTTP_ERROR")


def _default_error_message(status_code: int) -> str:
    return {
        400: "Invalid request",
        401: "Unauthorized",
        403: "Forbidden",
        404: "Resource not found",
        409: "Conflict",
        412: "Resource version is stale",
        422: "Request validation failed",
        429: "Request rate limit exceeded",
        500: "Internal server error",
        503: "Service unavailable",
    }.get(status_code, "Request failed")


app.include_router(moderation.router)
app.include_router(iam.router)
app.include_router(policy_reasons.router)
app.include_router(policies.router)
app.include_router(operations.router)
app.include_router(complaints.router)
app.include_router(appeals.router)
app.include_router(audit_exports.router)
app.include_router(bulk_operations.router)
app.include_router(sessions.router)
app.include_router(taxonomy.router)
app.include_router(products.router)
app.include_router(sellers.router)
app.include_router(integrations.router)
