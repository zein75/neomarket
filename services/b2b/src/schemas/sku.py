from uuid import UUID

from pydantic import BaseModel, ConfigDict


class SKUCreate(BaseModel):
    name: str
    price: int
    stock: int = 0


class SKUUpdate(BaseModel):
    name: str | None = None
    price: int | None = None
    stock: int | None = None
    is_active: bool | None = None


class SKUResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    price: int
    stock: int
    is_active: bool
