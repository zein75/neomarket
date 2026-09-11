from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr


class SellerCreate(BaseModel):
    email: EmailStr
    password: str
    company_name: str


class SellerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    company_name: str
    is_active: bool


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
