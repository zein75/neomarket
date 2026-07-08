from sqlalchemy.ext.asyncio import AsyncSession

from src.models.invoice import Invoice, InvoiceItem
from src.schemas.invoice import InvoiceItemCreate
from .base import BaseRepository


class InvoiceRepository(BaseRepository[Invoice]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Invoice)

    async def create_invoice(
        self,
        *,
        seller_id,
        items: list[InvoiceItemCreate],
    ) -> Invoice:
        invoice = Invoice(
            seller_id=seller_id,
            items=[
                InvoiceItem(
                    sku_id=item.sku_id,
                    quantity=item.quantity,
                    accepted_quantity=None,
                )
                for item in items
            ],
        )
        self.session.add(invoice)
        await self.session.flush()
        await self.session.refresh(invoice)
        return invoice
