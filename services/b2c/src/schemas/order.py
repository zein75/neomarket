from uuid import UUID

from pydantic import BaseModel, ConfigDict

from src.models.order import OrderStatus


class OrderItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sku_id: UUID
    product_id: UUID
    product_title: str
    sku_name: str
    quantity: int
    unit_price: int
    line_total: int


class OrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: OrderStatus
    total_amount: int
    currency: str
    items: list[OrderItemResponse] = []
