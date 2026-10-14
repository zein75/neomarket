import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class StockAdjustment(Base, TimestampMixin):
    """Auditable seller-originated stock change."""

    __tablename__ = "stock_adjustments"
    __table_args__ = (
        CheckConstraint("delta <> 0", name="ck_stock_adjustments_delta_nonzero"),
    )

    adjustment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    sku_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("skus.id", ondelete="RESTRICT"), nullable=False
    )
    delta: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    seller_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), unique=True)
