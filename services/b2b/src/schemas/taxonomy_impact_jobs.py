from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.schemas.admin_taxonomy import TaxonomyImpactPreviewResponse


class TaxonomyImpactJobResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: UUID
    status: Literal["QUEUED", "RUNNING", "COMPLETED", "FAILED"]
    stage: Literal["CATEGORIES", "PRODUCTS", "FINALIZE"]
    processed_categories: int = Field(ge=0)
    total_categories: int = Field(ge=0)
    processed_products: int = Field(ge=0)
    total_products: int = Field(ge=0)
    error_code: str | None = None
    result: TaxonomyImpactPreviewResponse | None = None
