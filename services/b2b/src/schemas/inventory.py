from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class SellerInventoryItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sku_id: UUID
    product_id: UUID
    product_title: str
    sku_name: str
    seller_article: str | None = None
    status: str
    category: str | None = None
    stock_quantity: int
    reserved_quantity: int
    active_quantity: int
    is_active: bool
    revision: int


class SellerInventoryResponse(BaseModel):
    items: list[SellerInventoryItem]
    page: dict[str, str | bool | None]


class SellerDashboardMetrics(BaseModel):
    as_of: datetime
    metrics: dict[str, int]
    definitions: dict[str, str]
