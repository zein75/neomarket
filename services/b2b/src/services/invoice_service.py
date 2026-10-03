from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.product import ProductStatus
from src.models.invoice import Invoice
from src.repositories.invoice_repo import InvoiceRepository
from src.repositories.sku_repo import SKURepository
from src.schemas.invoice import InvoiceCreate


class InvoiceService:
    def __init__(self, session: AsyncSession) -> None:
        self.invoice_repo = InvoiceRepository(session)
        self.sku_repo = SKURepository(session)

    async def create(self, seller_id: UUID, data: InvoiceCreate) -> Invoice:
        if not data.items:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "INVALID_REQUEST",
                    "message": "Invoice must contain at least one item",
                },
            )

        seen_sku_ids = set()
        for item in data.items:
            if item.sku_id in seen_sku_ids:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "code": "INVALID_REQUEST",
                        "message": "Duplicate SKU in invoice",
                    },
                )
            seen_sku_ids.add(item.sku_id)

            sku = await self.sku_repo.get_with_product(item.sku_id)
            if not sku:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "code": "SKU_NOT_FOUND",
                        "message": "SKU not found",
                    },
                )
            if sku.product.seller_id != seller_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={
                        "code": "SKU_ACCESS_DENIED",
                        "message": "Access denied",
                    },
                )
            if str(sku.product.status) != ProductStatus.MODERATED.value:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "code": "INVALID_REQUEST",
                        "message": "Invoice can include only moderated product SKUs",
                    },
                )

        return await self.invoice_repo.create_invoice(
            seller_id=seller_id,
            items=data.items,
        )
