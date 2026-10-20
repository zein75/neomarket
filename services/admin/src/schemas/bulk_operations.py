from uuid import UUID
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator


class BulkInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_ids: list[UUID] = Field(min_length=1, json_schema_extra={"uniqueItems": True})
    action: str = Field(min_length=1, max_length=64, pattern=r"^[A-Z][A-Z0-9_]*$")
    reason_code: str = Field(min_length=1, max_length=64, pattern=r"^[A-Z][A-Z0-9_]*$")
    expected_versions: dict[UUID, Annotated[int, Field(ge=1)]] | None = None

    @model_validator(mode="after")
    def validate_selection(self) -> "BulkInput":
        if len(self.target_ids) != len(set(self.target_ids)):
            raise ValueError("target_ids must be unique")
        if self.expected_versions is not None and set(self.expected_versions) != set(self.target_ids):
            raise ValueError("expected_versions must contain exactly one version for every target")
        return self
