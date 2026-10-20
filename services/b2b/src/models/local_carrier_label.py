import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class LocalCarrierLabel(Base, TimestampMixin):
    """Durable local transport receipt used only by the non-production simulator."""

    __tablename__ = "local_carrier_labels"
    __table_args__ = (
        UniqueConstraint("shipment_id", name="uq_local_carrier_label_shipment"),
        UniqueConstraint("operation_ref", name="uq_local_carrier_label_operation_ref"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    shipment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("seller_shipments.id", ondelete="CASCADE"), nullable=False
    )
    operation_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    tracking_number: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
