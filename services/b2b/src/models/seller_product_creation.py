import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class SellerProductCreation(Base, TimestampMixin):
    """Idempotency receipt for the atomic product and first SKU command."""

    __tablename__ = "seller_product_creations"
    __table_args__ = (
        UniqueConstraint("operation_id", name="uq_seller_product_creations_operation_id"),
    )
    seller_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sellers.id", ondelete="CASCADE"), primary_key=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    product_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    operation_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), default=uuid.uuid4, nullable=False
    )
