from uuid import UUID

from pydantic import BaseModel, Field


class SellerMediaIntentCreate(BaseModel):
    size: int = Field(ge=1, le=10_000_000)
    content_type: str = Field(pattern=r"^image/(jpeg|png|webp)$")
    sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")


class SellerMediaIntentResponse(BaseModel):
    id: UUID
    upload_url: str
    expires_at: str
    state: str


class SellerMediaStatusResponse(BaseModel):
    id: UUID
    state: str
    error_code: str | None = None
    content_type: str | None = None
    width: int | None = None
    height: int | None = None
