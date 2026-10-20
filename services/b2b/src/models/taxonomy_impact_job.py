import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, JSON, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class TaxonomyImpactJob(Base):
    __tablename__ = "taxonomy_impact_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('QUEUED', 'RUNNING', 'COMPLETED', 'FAILED')",
            name="ck_taxonomy_impact_jobs_status",
        ),
        CheckConstraint(
            "stage IN ('CATEGORIES', 'PRODUCTS', 'FINALIZE')",
            name="ck_taxonomy_impact_jobs_stage",
        ),
        CheckConstraint("processed_categories >= 0 AND processed_products >= 0", name="ck_taxonomy_impact_jobs_progress"),
        Index("ix_taxonomy_impact_jobs_worker", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id", ondelete="RESTRICT"), nullable=False
    )
    change_type: Mapped[str] = mapped_column(String(16), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    taxonomy_version: Mapped[int] = mapped_column(Integer, nullable=False)
    category_version: Mapped[int] = mapped_column(Integer, nullable=False)
    request: Mapped[dict[str, object]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="QUEUED")
    stage: Mapped[str] = mapped_column(String(16), nullable=False, default="CATEGORIES")
    category_cursor: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    product_cursor: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    total_categories: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_categories: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_products: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_product_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    products_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processed_products: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    affected_sellers: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    invalid_products: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    requires_reapproval: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warnings: Mapped[list[str]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False, default=list
    )
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result: Mapped[dict[str, object] | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class TaxonomyImpactRedirect(Base):
    __tablename__ = "taxonomy_impact_redirects"
    __table_args__ = (Index("ix_taxonomy_impact_redirects_job", "job_id", "category_id"),)

    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("taxonomy_impact_jobs.id", ondelete="CASCADE"), primary_key=True
    )
    category_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    old_path: Mapped[str] = mapped_column(String(4096), nullable=False)
    new_path: Mapped[str] = mapped_column(String(4096), nullable=False)
