from types import SimpleNamespace
from uuid import UUID

from fastapi import APIRouter, Depends, Header

from src.api.deps import require_permission
from src.api.router import AdminAPIRoute
from src.api.unavailable import dependency_not_configured
from src.schemas.admin import AdminOperationResponse
from src.schemas.bulk_operations import BulkInput
from src.schemas.taxonomy import ImpactPreviewResponse


router = APIRouter(route_class=AdminAPIRoute, tags=["bulk-operations"])


@router.post(
    "/admin/v1/bulk-operations/preview",
    response_model=ImpactPreviewResponse,
    response_model_exclude_none=True,
    operation_id="POST_admin_v1_bulk_operations_preview",
    responses={503: {"description": "Bulk impact preview is not configured"}},
)
async def preview_bulk_operation(
    data: BulkInput,
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    _: SimpleNamespace = Depends(require_permission("bulk.preview")),
) -> ImpactPreviewResponse:
    raise dependency_not_configured("B2B", "bulk operation impact preview")


@router.post(
    "/admin/v1/bulk-operations",
    response_model=AdminOperationResponse,
    status_code=202,
    operation_id="POST_admin_v1_bulk_operations",
    responses={503: {"description": "Bulk operations are not configured"}},
)
async def propose_bulk_operation(
    data: BulkInput,
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    _: SimpleNamespace = Depends(require_permission("bulk.propose")),
) -> AdminOperationResponse:
    raise dependency_not_configured("B2B", "bulk operation execution")
