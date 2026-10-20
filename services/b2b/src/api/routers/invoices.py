from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db, require_seller_permission
from src.models.seller import Seller
from src.schemas.invoice import InvoiceCreate, InvoiceResponse
from src.services.invoice_service import InvoiceService

router = APIRouter(tags=["invoices"])
finance_seller_permission = require_seller_permission("finance.manage")


@router.post("/api/v1/invoices", response_model=InvoiceResponse, status_code=201)
async def create_invoice(
    data: InvoiceCreate,
    current_seller: Seller = Depends(finance_seller_permission),
    db: AsyncSession = Depends(get_db),
) -> Any:
    invoice = await InvoiceService(db).create(current_seller.id, data)
    await db.commit()
    return invoice
