from datetime import datetime
from typing import Any, Literal
from uuid import UUID
import re
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TaxonomyCommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: UUID
    command_type: Literal[
        "CATEGORY_CREATE", "CATEGORY_UPDATE", "CATEGORY_MOVE",
        "CATEGORY_ARCHIVE", "CATEGORY_PUBLISH", "ATTRIBUTE_RULES_PUBLISH",
        "ATTRIBUTE_CREATE", "ATTRIBUTE_UPDATE", "BRAND_CREATE", "BRAND_UPDATE",
        "BRAND_VERIFY", "BRAND_MERGE",
    ]
    aggregate_id: UUID
    expected_version: int = Field(ge=1)
    impact_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    payload: dict[str, Any]
    requested_by_staff_id: UUID
    approved_by_staff_id: UUID
    reason_code: str = Field(min_length=1, max_length=64)
    occurred_at: datetime


class TaxonomyCommandReceiptResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: UUID
    status: Literal["APPLIED", "CONFLICT", "REJECTED"]
    result: dict[str, Any] = Field(default_factory=dict)


class CategoryCreatePayload(BaseModel):
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
        return _validated_labels(value)


class CategoryUpdatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str | None = Field(default=None, min_length=1, max_length=80)
    slug: str | None = Field(default=None, min_length=1, max_length=160)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    labels: dict[str, str] = Field(default_factory=dict, max_length=20)
    description: str | None = Field(default=None, max_length=5000)
    sort_order: int | None = None
    seo_title: str | None = Field(default=None, max_length=255)
    image_media_id: UUID | None = None

    @field_validator("labels")
    @classmethod
    def validate_labels(cls, value: dict[str, str]) -> dict[str, str]:
        return _validated_labels(value)


def _validated_labels(value: dict[str, str]) -> dict[str, str]:
    labels: dict[str, str] = {}
    seen: set[str] = set()
    for locale, label in value.items():
        normalized_locale = locale.strip()
        normalized_label = label.strip()
        if not re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", normalized_locale):
            raise ValueError("locale must be a BCP 47 language tag")
        if not normalized_label or len(normalized_label) > 255:
            raise ValueError("localized label must contain 1 to 255 characters")
        if normalized_locale.casefold() in seen:
            raise ValueError("locale tags must be unique regardless of case")
        seen.add(normalized_locale.casefold())
        labels[normalized_locale] = normalized_label
    return labels


class CategoryMovePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_parent_id: UUID
    position: int | None = Field(default=None, ge=0)
    impact_hash: str = Field(min_length=1, max_length=128)


class CategoryRulePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attribute_id: UUID
    required: bool
    filterable: bool | None = None
    variant_dimension: bool | None = None
    condition: dict[str, Any] | None = None


class TaxonomyImpactPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    change_type: Literal["MOVE", "ARCHIVE", "SCHEMA_UPDATE"]
    new_parent_id: UUID | None = None
    proposed_rules: list[CategoryRulePayload] | None = None


class TaxonomyImpactRedirect(BaseModel):
    model_config = ConfigDict(extra="forbid")

    old_path: str
    new_path: str


class TaxonomyImpactPreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    change_id: UUID
    affected_products: int = Field(ge=0)
    affected_sellers: int = Field(ge=0)
    affected_categories: int = Field(ge=0)
    invalid_products: int = Field(ge=0)
    requires_reapproval: int = Field(ge=0)
    redirects: list[TaxonomyImpactRedirect]
    warnings: list[str]
    hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class CategoryRulesPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(ge=1)
    rules: list[CategoryRulePayload]


class AttributeDefinitionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_]*$")
    name: str = Field(min_length=1, max_length=255)
    data_type: Literal["string", "integer", "decimal", "boolean", "enum", "multi_enum", "date", "reference"]
    unit: str | None = Field(default=None, max_length=80)
    constraints: dict[str, Any] = Field(default_factory=dict)
    required: bool = False
    filterable: bool = False
    searchable: bool = False
    comparable: bool = False
    variant_dimension: bool = False
    pii: bool = False

    @model_validator(mode="after")
    def validate_constraints(self) -> "AttributeDefinitionPayload":
        allowed_keys = {"min", "max", "min_length", "max_length", "allowed_values", "options", "pattern"}
        if set(self.constraints) - allowed_keys:
            raise ValueError("unsupported attribute constraint")
        if "allowed_values" in self.constraints and "options" in self.constraints:
            raise ValueError("use only one enum value list")
        values = self.constraints.get("allowed_values", self.constraints.get("options"))
        if self.data_type in {"enum", "multi_enum"}:
            if not isinstance(values, list) or not values or len(values) > 500 or any(not isinstance(value, str) or not value for value in values):
                raise ValueError("enum attributes require a bounded list of strings")
            if len(values) != len(set(values)):
                raise ValueError("enum values must be unique")
        elif values is not None:
            raise ValueError("allowed values are supported only for enum attributes")
        for key in ("min_length", "max_length"):
            value = self.constraints.get(key)
            if value is not None and (type(value) is not int or not 0 <= value <= 10000):
                raise ValueError("invalid string length constraint")
        if self.data_type != "string" and any(key in self.constraints for key in ("min_length", "max_length", "pattern")):
            raise ValueError("string constraints require string data type")
        pattern = self.constraints.get("pattern")
        if pattern is not None:
            if not isinstance(pattern, str) or len(pattern) > 128 or re.search(r"\\[1-9]|\([^)]*[+*][^)]*\)[+*{]", pattern):
                raise ValueError("pattern is too complex")
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError("invalid pattern") from exc
        if self.data_type not in {"integer", "decimal"} and any(key in self.constraints for key in ("min", "max")):
            raise ValueError("numeric bounds require numeric data type")
        bounds: dict[str, Decimal] = {}
        for key in ("min", "max"):
            value = self.constraints.get(key)
            if value is not None:
                if isinstance(value, bool):
                    raise ValueError("numeric bounds must be finite numbers")
                try:
                    bound = Decimal(str(value))
                except InvalidOperation as exc:
                    raise ValueError("numeric bounds must be finite numbers") from exc
                if not bound.is_finite():
                    raise ValueError("numeric bounds must be finite numbers")
                bounds[key] = bound
        if "min" in bounds and "max" in bounds and bounds["min"] > bounds["max"]:
            raise ValueError("minimum cannot exceed maximum")
        return self


class BrandDefinitionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    aliases: list[str] = Field(default_factory=list, max_length=100)
    evidence_ref: str | None = Field(default=None, min_length=1, max_length=2048)

    @model_validator(mode="after")
    def normalize_inputs(self) -> "BrandDefinitionPayload":
        self.name = self.name.strip()
        if not self.name:
            raise ValueError("brand name must not be blank")
        normalized = [alias.strip().casefold() for alias in self.aliases]
        if any(not alias for alias in normalized) or len(set(normalized)) != len(normalized):
            raise ValueError("brand aliases must be non-empty and unique")
        self.aliases = [alias.strip() for alias in self.aliases]
        if self.name.casefold() in normalized:
            raise ValueError("brand name cannot also be its alias")
        return self


class BrandMergePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_brand_id: UUID
    impact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason_code: str = Field(min_length=1, max_length=64, pattern=r"^[A-Z][A-Z0-9_]*$")


class BrandMergePreviewRequest(BaseModel):
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
