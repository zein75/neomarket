import base64
import binascii
import hashlib
import hmac
import json
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import FileResponse
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db, require_seller_permission
from src.core.config import settings
from src.core.redis import get_redis
from src.models.seller import Seller
from src.schemas.inventory import SellerDashboardMetrics, SellerInventoryResponse
from src.schemas.inventory_import import InventoryImportCreate, InventoryImportResponse
from src.schemas.inventory_export import InventoryExportCreate, InventoryExportResponse
from src.services.inventory_service import SellerInventoryService
from src.services.inventory_export_service import InventoryExportService
from src.services.inventory_import_service import InventoryImportService
from src.services.inventory_export_rate_limiter import check_inventory_export_rate_limit

router = APIRouter(tags=["seller-inventory"])


def _inventory_export_response(job) -> InventoryExportResponse:
    return InventoryExportResponse(
        id=job.id,
        state=job.state,
        row_count=job.row_count,
        created_at=job.created_at,
        generated_at=job.generated_at,
        expires_at=job.expires_at,
        sha256=job.sha256,
        failure_code=job.failure_code,
        download_token=InventoryExportService.download_token(job),
    )


@router.post(
    "/api/v1/seller/inventory/exports",
    response_model=InventoryExportResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_inventory_export(
    data: InventoryExportCreate,
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    seller: Seller = Depends(require_seller_permission("inventory.read")),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> InventoryExportResponse:
    await check_inventory_export_rate_limit(redis, seller.id)
    try:
        job = await InventoryExportService(db).create(seller.id, idempotency_key, data)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "INVENTORY_EXPORT_IDEMPOTENCY_CONFLICT", "message": str(exc)},
        ) from exc
    await db.commit()
    return _inventory_export_response(job)


@router.get(
    "/api/v1/seller/inventory/exports/{job_id}",
    response_model=InventoryExportResponse,
)
async def get_inventory_export(
    job_id: UUID,
    seller: Seller = Depends(require_seller_permission("inventory.read")),
    db: AsyncSession = Depends(get_db),
) -> InventoryExportResponse:
    job = await InventoryExportService(db).get(seller.id, job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "INVENTORY_EXPORT_NOT_FOUND"})
    return _inventory_export_response(job)


@router.get("/api/v1/seller/inventory/exports/{job_id}/download", include_in_schema=False)
async def download_inventory_export(
    job_id: UUID,
    token: str = Query(min_length=16, max_length=1024),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    try:
        result = await InventoryExportService(db).download_path(job_id, token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"code": "INVALID_EXPORT_LINK"}) from exc
    if not result:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail={"code": "INVENTORY_EXPORT_EXPIRED"})
    path, _generated_at = result
    return FileResponse(
        path,
        media_type="text/csv; charset=utf-8",
        filename=f"seller-inventory-{job_id}.csv",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


def _encode_cursor(
    seller_id: UUID,
    product_id: UUID,
    sku_id: UUID,
    query: str | None,
    status_filter: str | None,
) -> str:
    payload = json.dumps(
        {
            "seller_id": str(seller_id),
            "product_id": str(product_id),
            "sku_id": str(sku_id),
            "query": query,
            "status": status_filter,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    signature = hmac.new(settings.secret_key.encode(), payload, hashlib.sha256).digest()
    return (
        f"{base64.urlsafe_b64encode(payload).decode().rstrip('=')}."
        f"{base64.urlsafe_b64encode(signature).decode().rstrip('=')}"
    )


def _decode_cursor(
    cursor: str | None,
    seller_id: UUID,
    query: str | None = None,
    status_filter: str | None = None,
) -> tuple[UUID, UUID] | None:
    if not cursor:
        return None
    try:
        encoded, signed = cursor.split(".", 1)
        payload = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        signature = base64.urlsafe_b64decode(signed + "=" * (-len(signed) % 4))
        # Python's base64 decoder accepts non-canonical trailing bits.  Reject
        # those forms so changing a single visible cursor character cannot be
        # silently normalized into the original signed bytes.
        if base64.urlsafe_b64encode(payload).decode().rstrip("=") != encoded:
            raise ValueError("non-canonical cursor payload")
        if base64.urlsafe_b64encode(signature).decode().rstrip("=") != signed:
            raise ValueError("non-canonical cursor signature")
        expected = hmac.new(settings.secret_key.encode(), payload, hashlib.sha256).digest()
        data = json.loads(payload)
        if not hmac.compare_digest(signature, expected):
            raise ValueError("bad cursor signature")
        if data.get("seller_id") != str(seller_id):
            raise ValueError("cursor belongs to another seller")
        if data.get("query") != query or data.get("status") != status_filter:
            raise ValueError("cursor belongs to another inventory filter")
        return UUID(data["product_id"]), UUID(data["sku_id"])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError, binascii.Error) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "INVALID_CURSOR", "message": "Seller inventory cursor is invalid"},
        ) from exc


@router.get("/api/v1/seller/inventory", response_model=SellerInventoryResponse)
async def list_seller_inventory(
    cursor: str | None = Query(default=None, max_length=1024),
    limit: int = Query(default=50, ge=1, le=100),
    query: str | None = Query(default=None, max_length=120),
    status_filter: Literal["available", "reserved", "unavailable", "inactive"] | None = Query(default=None, alias="status"),
    seller: Seller = Depends(require_seller_permission("inventory.read")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    normalized_query = query.strip() if query and query.strip() else None
    result = await SellerInventoryService(db).list_for_seller(
        seller.id,
        limit=limit,
        cursor=_decode_cursor(cursor, seller.id, normalized_query, status_filter),
        query=normalized_query,
        status_filter=status_filter,
    )
    position = result["next_cursor"]
    return {
        "items": result["items"],
        "page": {
            "has_more": result["has_more"],
            "next_cursor": (
                _encode_cursor(seller.id, position[0], position[1], normalized_query, status_filter)
                if position
                else None
            ),
        },
    }


@router.get("/api/v1/seller/dashboard/metrics", response_model=SellerDashboardMetrics)
async def get_seller_dashboard_metrics(
    seller: Seller = Depends(require_seller_permission("inventory.read")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    return await SellerInventoryService(db).get_dashboard_metrics(seller.id)


def _import_response(job) -> dict[str, object]:
    rows = list(job.rows)
    return {
        "id": job.id,
        "mode": job.mode,
        "source_sha256": job.source_sha256,
        "state": job.state,
        "total_rows": len(rows),
        "valid_rows": sum(row.state in {"VALID", "UNCHANGED", "APPLIED"} for row in rows),
        "error_rows": sum(row.state in {"INVALID", "CONFLICT"} for row in rows),
        "applied_rows": sum(row.state == "APPLIED" for row in rows),
        "committed_at": job.committed_at,
        "rows": rows,
    }


@router.post("/api/v1/seller/inventory/imports", response_model=InventoryImportResponse, status_code=201)
async def preview_inventory_import(
    data: InventoryImportCreate,
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    seller: Seller = Depends(require_seller_permission("inventory.adjust")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    job = await InventoryImportService(db).create_preview(seller.id, idempotency_key, data)
    await db.commit()
    return _import_response(job)


@router.get("/api/v1/seller/inventory/imports/{job_id}", response_model=InventoryImportResponse)
async def get_inventory_import(
    job_id: UUID,
    seller: Seller = Depends(require_seller_permission("inventory.read")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    job = await InventoryImportService(db).get(seller.id, job_id)
    return _import_response(job)


@router.post("/api/v1/seller/inventory/imports/{job_id}/commit", response_model=InventoryImportResponse)
async def commit_inventory_import(
    job_id: UUID,
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    seller: Seller = Depends(require_seller_permission("inventory.adjust")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    job = await InventoryImportService(db).commit(seller.id, job_id, idempotency_key)
    await db.commit()
    return _import_response(job)
