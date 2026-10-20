from datetime import datetime
from typing import Literal
from uuid import UUID

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CategoryView(BaseModel):
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
    updated_at: datetime | None = None


class CategoryTreeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[CategoryView]
    taxonomy_version: int = Field(ge=1)


class AttributeDefinitionView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    code: str
    name: str
    data_type: Literal["string", "integer", "decimal", "boolean", "enum", "multi_enum", "date", "reference"]
    unit: str | None = None
    required: bool | None = None
    filterable: bool | None = None
    searchable: bool | None = None
    comparable: bool | None = None
    variant_dimension: bool | None = None
    pii: bool | None = None
    constraints: dict[str, object] | None = None
    version: int = Field(ge=1)


class PageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    has_more: bool
    next_cursor: str | None = None


class BrandView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    aliases: list[str] = Field(default_factory=list)
    status: Literal["DRAFT", "VERIFIED", "RESTRICTED", "MERGED"]
    evidence_ref: str | None = None
    merged_into_id: UUID | None = None
    version: int = Field(ge=1)


class BrandPageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[BrandView]
    page: PageResponse


class ImpactRedirect(BaseModel):
    model_config = ConfigDict(extra="forbid")

    old_path: str = Field(default=None)
    new_path: str = Field(default=None)


class ImpactPreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    change_id: UUID
    affected_products: int = Field(ge=0)
    affected_sellers: int = Field(default=0, ge=0)
    affected_categories: int = Field(ge=0)
    invalid_products: int = Field(ge=0)
    requires_reapproval: int = Field(ge=0)
    redirects: list[ImpactRedirect] = Field(default_factory=list)
    warnings: list[str]
    hash: str


class ImpactPreviewJobResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: UUID
    status: Literal["QUEUED", "RUNNING", "COMPLETED", "FAILED"]
    stage: Literal["CATEGORIES", "PRODUCTS", "FINALIZE"]
    processed_categories: int = Field(ge=0)
    total_categories: int = Field(ge=0)
    processed_products: int = Field(ge=0)
    total_products: int = Field(ge=0)
    error_code: str | None = None
    result: ImpactPreviewResponse | None = None


class AttributePageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[AttributeDefinitionView]
    page: PageResponse


class CategoryRuleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attribute_id: UUID
    required: bool
    filterable: bool | None = None
    variant_dimension: bool | None = None
    condition: dict[str, object] | None = None


class CategoryRulePageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[CategoryRuleInput]
    schema_version: int = Field(ge=0)


class CategoryRuleSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(ge=1)
    rules: list[CategoryRuleInput]
    impact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class AttributeValues(BaseModel):
    model_config = ConfigDict(extra="forbid", title="AttributeValues")

    values: dict[str, object]


class SchemaValidationError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_path: str = Field(default=None)
    code: str = Field(default=None)
    message: str = Field(default=None)


class SchemaValidationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valid: bool
    errors: list[SchemaValidationError]


class CategoryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parent_id: UUID | None = None
    code: str = Field(min_length=1, max_length=80)
    slug: str = Field(min_length=1, max_length=160)
    name: str = Field(min_length=1, max_length=255)
    labels: dict[str, str] = Field(default_factory=dict, max_length=20)
    description: str | None = Field(default=None, max_length=5000)
    sort_order: int | None = None
    seo_title: str | None = Field(default=None, max_length=255)
    image_media_id: UUID | None = None

    @field_validator("labels")
    @classmethod
    def validate_labels(cls, value: dict[str, str]) -> dict[str, str]:
        labels: dict[str, str] = {}
        seen: set[str] = set()
        for locale, label in value.items():
            locale = locale.strip()
            label = label.strip()
            if not re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", locale):
                raise ValueError("locale must be a BCP 47 language tag")
            if not label or len(label) > 255:
                raise ValueError("localized label must contain 1 to 255 characters")
            if locale.casefold() in seen:
                raise ValueError("locale tags must be unique regardless of case")
            seen.add(locale.casefold())
            labels[locale] = label
        return labels


class CategoryMoveInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_parent_id: UUID
    position: int | None = Field(default=None, ge=0)
    impact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class CategoryArchiveInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason_code: str = Field(min_length=1, max_length=64, pattern=r"^[A-Z][A-Z0-9_]*$")
    comment: str | None = Field(default=None, max_length=3000)
    impact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class AttributeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_]*$")
    name: str = Field(min_length=1, max_length=255)
    data_type: Literal["string", "integer", "decimal", "boolean", "enum", "multi_enum", "date", "reference"]
    unit: str | None = None
    constraints: dict[str, object] = Field(default_factory=dict)
    required: bool = False
    filterable: bool = False
    searchable: bool = False
    comparable: bool = False
    variant_dimension: bool = False
    pii: bool = False


class BrandInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    aliases: list[str] = Field(default_factory=list, max_length=100)
    evidence_ref: str | None = Field(default=None, min_length=1, max_length=2048)


class BrandVerificationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_ref: str = Field(min_length=1, max_length=2048)
    reason_code: str = Field(min_length=1, max_length=64, pattern=r"^[A-Z][A-Z0-9_]*$")


class BrandMergePreviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_brand_id: UUID


class BrandMergePreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    change_id: UUID
    source_brand_id: UUID
    target_brand_id: UUID
    affected_products: int = Field(ge=0)
    hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    expires_at: datetime


class BrandMergeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_brand_id: UUID
    impact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason_code: str = Field(min_length=1, max_length=64, pattern=r"^[A-Z][A-Z0-9_]*$")


class ImpactPreviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    change_type: Literal["MOVE", "ARCHIVE", "SCHEMA_UPDATE"]
    new_parent_id: UUID | None = None
    proposed_rules: list[CategoryRuleInput] | None = None
