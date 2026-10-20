from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .taxonomy import PageResponse


class B2BProductSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: UUID
    seller_id: UUID
    published_revision: int | None = Field(default=None, ge=1)
    current_revision: int = Field(ge=1)
    visible: bool
    visibility_reasons: list[str]


class B2BProductPageCursor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    has_more: bool
    next_cursor: str | None = None


class B2BProductPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[B2BProductSummary]
    page: B2BProductPageCursor


class ProductOverview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    seller_id: UUID
    published_revision: int | None = Field(default=None, ge=1)
    current_revision: int = Field(default=None, ge=1)
    visible: bool
    visibility_reasons: list[str] = Field(default_factory=list)


class ProductPublication(BaseModel):
    model_config = ConfigDict(extra="ignore")

    product_id: UUID
    current_revision: int = Field(ge=1)
    published_revision: int | None = Field(default=None, ge=1)
    visible: bool
    visibility_reasons: list[str]


class ProductRevisionSnapshot(BaseModel):
    model_config = ConfigDict(extra="ignore")

    product_id: UUID
    seller_id: UUID
    revision: int = Field(ge=1)
    snapshot_hash: str
    content: dict[str, object]
    media_refs: list[str]


class ProductPageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ProductOverview]
    page: PageResponse


class HoldInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason_code: str = Field(min_length=1, max_length=64, pattern=r"^[A-Z][A-Z0-9_]*$")
    expires_at: datetime
    comment: str | None = Field(default=None, max_length=3000)

    @field_validator("expires_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("expires_at must include timezone information")
        return value
