from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProductPublicationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: UUID
    current_revision: int = Field(ge=1)
    published_revision: int | None = Field(default=None, ge=1)
    visible: bool
    visibility_reasons: list[str]
    updated_at: datetime


class AdminProductSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: UUID
    seller_id: UUID
    current_revision: int = Field(ge=1)
    published_revision: int | None = Field(default=None, ge=1)
    visible: bool
    visibility_reasons: list[str]


class AdminPageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    has_more: bool
    next_cursor: str | None = None


class AdminProductPageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[AdminProductSummaryResponse]
    page: AdminPageResponse


class AdminTaxonomyCategoryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    parent_id: UUID | None = None
    code: str
    slug: str
    name: str
    labels: dict[str, str] = Field(default_factory=dict)
    description: str | None = None
    status: Literal["DRAFT", "REVIEW_PENDING", "ACTIVE", "HIDDEN", "ARCHIVED"]
    sort_order: int | None = None
    version: int = Field(ge=1)
    path: str | None = None
    seo_title: str | None = None
    image_media_id: UUID | None = None
    schema_version: int = Field(ge=0)
    attribute_rules: list[dict[str, object]]
    updated_at: datetime


class AdminTaxonomyAttributeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    code: str
    name: str
    data_type: Literal["string", "integer", "decimal", "boolean", "enum", "multi_enum", "date", "reference"]
    unit: str | None = None
    required: bool
    filterable: bool
    searchable: bool
    comparable: bool
    variant_dimension: bool
    pii: bool
    constraints: dict[str, object]
    version: int = Field(ge=1)


class AdminBrandResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    aliases: list[str]
    status: Literal["DRAFT", "VERIFIED", "RESTRICTED", "MERGED"]
    evidence_ref: str | None = None
    merged_into_id: UUID | None = None
    version: int = Field(ge=1)


class AdminTaxonomySnapshotResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    categories: list[AdminTaxonomyCategoryResponse]
    attributes: list[AdminTaxonomyAttributeResponse]
    brands: list[AdminBrandResponse]
    as_of: datetime


class ProductRevisionSnapshotResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: UUID
    seller_id: UUID
    revision: int = Field(ge=1)
    snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    content: dict[str, object]
    media_refs: list[str]


class SafetyHoldPayload(BaseModel):
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


class ServiceCommandReceiptResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: UUID
    status: Literal["QUEUED", "APPLIED", "CONFLICT", "REJECTED"]
    aggregate_version: int | None = Field(default=None, ge=0)
    message: str | None = None
    result: dict[str, object] | None = None
