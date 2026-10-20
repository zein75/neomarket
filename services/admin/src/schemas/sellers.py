from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SellerRestrictionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["RESTRICT", "SUSPEND", "REINSTATE"]
    reason_code: str = Field(min_length=1, max_length=64, pattern=r"^[A-Z][A-Z0-9_]*$")
    comment: str | None = Field(default=None, max_length=3000)
    effective_until: datetime | None = None

    @field_validator("effective_until")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("effective_until must include timezone information")
        return value
