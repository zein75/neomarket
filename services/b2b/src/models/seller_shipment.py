import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin

if TYPE_CHECKING:
    from .seller_order import SellerOrder
    from .seller_carrier_operation import SellerCarrierOperation


class SellerShipment(Base, TimestampMixin):
    """Seller-owned packed parcel manifest; no carrier is implied by PACKED."""

    __tablename__ = "seller_shipments"
    __table_args__ = (
        UniqueConstraint("seller_order_id", "idempotency_key", name="uq_seller_shipments_order_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    seller_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("seller_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    seller_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sellers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    idempotency_key: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PACKED")
    status_revision: Mapped[int] = mapped_column(default=0, nullable=False)
    packed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lines: Mapped[list["SellerShipmentLine"]] = relationship(
        back_populates="shipment", cascade="all, delete-orphan", lazy="selectin"
    )
    seller_order: Mapped["SellerOrder"] = relationship(back_populates="shipments")
    carrier_operation: Mapped["SellerCarrierOperation | None"] = relationship(
        back_populates="shipment", cascade="all, delete-orphan", uselist=False, lazy="selectin"
    )


class SellerShipmentLine(Base):
    __tablename__ = "seller_shipment_lines"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_seller_shipment_lines_quantity_positive"),
        UniqueConstraint("shipment_id", "seller_order_item_id", name="uq_seller_shipment_line_item"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    shipment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("seller_shipments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    seller_order_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("seller_order_items.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    quantity: Mapped[int] = mapped_column(nullable=False)
    shipment: Mapped[SellerShipment] = relationship(back_populates="lines")
