from datetime import datetime
from uuid import UUID

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class InvoiceItemCreate(BaseModel):
    sku_id: UUID
    quantity: int = Field(gt=0)


class InvoiceCreate(BaseModel):
    items: list[InvoiceItemCreate] = Field(
        validation_alias=AliasChoices("items", "invoice_items")
    )


class InvoiceItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID | None = None
    sku_id: UUID
    quantity: int
    accepted_quantity: int | None = None


class InvoiceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    seller_id: UUID
    status: str
    created_at: datetime
    updated_at: datetime
    items: list[InvoiceItemResponse]
