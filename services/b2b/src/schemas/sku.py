from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SKUCreate(BaseModel):
    product_id: UUID
    name: str
    price: int
    stock: int = 0
    images: list[str] = Field(min_length=1)


class SKUUpdate(BaseModel):
    name: str | None = None
    price: int | None = None
    stock: int | None = None
    images: list[str] | None = None
    is_active: bool | None = None


class SKUResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_id: UUID
    name: str
    price: int
    cost_price: int | None = None
    stock: int
    active_quantity: int | None = None
    reserved_quantity: int = 0
    images: list[str]
    is_active: bool
