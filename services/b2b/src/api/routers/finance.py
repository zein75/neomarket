from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.api.deps import require_seller_permission
from src.models.seller import Seller

router = APIRouter(tags=["seller-finance"])
finance_read = require_seller_permission("finance.read")
finance_manage = require_seller_permission("finance.manage")


def _feature_not_configured() -> None:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail={
            "code": "FEATURE_NOT_CONFIGURED",
            "message": "Seller finance is unavailable until a payment and commission provider is configured",
        },
        headers={"Cache-Control": "no-store"},
    )


@router.get("/api/v1/seller/finance/overview")
@router.get("/finance/overview", include_in_schema=False)
async def get_finance_overview(
    _: Seller = Depends(finance_read),
    period: str = Query(default="30d", max_length=32),
) -> None:
    _ = period
    _feature_not_configured()


@router.get("/api/v1/seller/finance/transactions")
@router.get("/finance/transactions", include_in_schema=False)
async def list_finance_transactions(
    _: Seller = Depends(finance_read),
) -> None:
    _feature_not_configured()


@router.get("/api/v1/seller/finance/settlements")
@router.get("/finance/settlements", include_in_schema=False)
async def list_finance_settlements(
    _: Seller = Depends(finance_read),
) -> None:
    _feature_not_configured()


@router.get("/api/v1/seller/finance/payouts")
@router.get("/finance/payouts", include_in_schema=False)
async def list_finance_payouts(
    _: Seller = Depends(finance_read),
) -> None:
    _feature_not_configured()


@router.get("/api/v1/seller/finance/statements/{statement_id}")
@router.get("/finance/statements/{statement_id}", include_in_schema=False)
async def get_finance_statement(
    statement_id: UUID,
    _: Seller = Depends(finance_read),
) -> None:
    _ = statement_id
    _feature_not_configured()


@router.post("/api/v1/seller/finance/payouts", status_code=501)
@router.post("/finance/payouts", status_code=501, include_in_schema=False)
async def create_payout(
    _: Seller = Depends(finance_manage),
) -> None:
    _feature_not_configured()
