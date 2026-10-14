from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class SellerCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=12, max_length=256)
    company_name: str = Field(min_length=1, max_length=255)


class SellerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    company_name: str
    is_active: bool


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
