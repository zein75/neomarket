import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class StockAdjustment(Base, TimestampMixin):
    """Auditable seller-originated stock change."""

    __tablename__ = "stock_adjustments"
    __table_args__ = (
        CheckConstraint("delta <> 0", name="ck_stock_adjustments_delta_nonzero"),
        UniqueConstraint(
            "seller_id", "idempotency_key", name="uq_stock_adjustments_seller_key"
        ),
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
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    request_hash: Mapped[str | None] = mapped_column(String(64))
    result_on_hand: Mapped[int | None] = mapped_column(Integer)
    result_reserved: Mapped[int | None] = mapped_column(Integer)
    ledger_entry_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
