from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class InventoryImportRowInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seller_article: str = Field(min_length=1, max_length=128)
    on_hand: int = Field(ge=0, le=10_000_000)

    @field_validator("seller_article")
    @classmethod
    def normalize_article(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("seller_article must not be blank")
        return normalized


class InventoryImportCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["COUNT"]
    source_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    reason: str = Field(min_length=3, max_length=64)
    rows: list[InventoryImportRowInput] = Field(min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def trim_reason(cls, value: str) -> str:
        result = value.strip()
        if len(result) < 3:
            raise ValueError("reason must contain at least 3 non-whitespace characters")
        return result

    @model_validator(mode="after")
    def reject_duplicate_articles(self) -> "InventoryImportCreate":
        articles = [row.seller_article.casefold() for row in self.rows]
        if len(articles) != len(set(articles)):
            raise ValueError("seller_article values must be unique within the import")
        return self


class InventoryImportRowResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    row_number: int
    seller_article: str
    target_on_hand: int
    before_on_hand: int | None
    delta: int | None
    state: Literal["VALID", "INVALID", "UNCHANGED", "APPLIED", "CONFLICT"]
    error_code: str | None
    error_message: str | None
    result_on_hand: int | None


class InventoryImportResponse(BaseModel):
    id: UUID
    mode: str
    source_sha256: str
    state: Literal["PREVIEWED", "COMMITTED", "PARTIAL"]
    total_rows: int
    valid_rows: int
    error_rows: int
    applied_rows: int
    committed_at: datetime | None
    rows: list[InventoryImportRowResponse]
