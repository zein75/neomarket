import uuid
from datetime import datetime
from enum import StrEnum
import re
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import mapped_column, Mapped, relationship

from .base import Base, TimestampMixin

if TYPE_CHECKING:
    from .seller import Seller
    from .sku import SKU


class ProductStatus(StrEnum):
    CREATED = "CREATED"
    ON_MODERATION = "ON_MODERATION"
    MODERATED = "MODERATED"
    BLOCKED = "BLOCKED"
    HARD_BLOCKED = "HARD_BLOCKED"


class Product(Base, TimestampMixin):
    __tablename__ = "products"
    __table_args__ = (
        Index("ix_products_seller_deleted_id", "seller_id", "deleted", "id"),
        Index(
            "ix_products_public_catalog",
            "status",
            "deleted",
            "category_id",
            "seller_id",
            "created_at",
        ),
        Index("ix_products_brand_id", "brand_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    seller_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sellers.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str | None] = mapped_column(String(320), nullable=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id", ondelete="RESTRICT"), nullable=True
    )
    brand_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("brands.id", ondelete="RESTRICT"), nullable=True
    )
    images: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    characteristics: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    blocking_reason: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    field_reports: Mapped[list[dict[str, object]]] = mapped_column(
        JSON, default=list, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(32), default=ProductStatus.CREATED.value, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    published_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    safety_hold_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    safety_hold_reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Keep the PostgreSQL JSONB storage while allowing the SQLite test/runtime
    # dialect to compile the model as regular JSON.  A raw JSONB column makes
    # metadata creation fail before reservation/inventory tests can run.
    published_snapshot: Mapped[dict[str, object] | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=True
    )

    seller: Mapped["Seller"] = relationship("Seller", back_populates="products")
    skus: Mapped[list["SKU"]] = relationship(
        "SKU", back_populates="product", cascade="all, delete-orphan"
    )

    @staticmethod
    def make_slug(title: str, product_id: uuid.UUID) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        return f"{slug or 'product'}-{str(product_id)[:8]}"
