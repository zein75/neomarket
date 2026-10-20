import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin

if TYPE_CHECKING:
    from .seller_shipment import SellerShipment


class SellerCarrierOperation(Base, TimestampMixin):
    __tablename__ = "seller_carrier_operations"
    __table_args__ = (
        UniqueConstraint("shipment_id", name="uq_seller_carrier_operation_shipment"),
        UniqueConstraint("idempotency_key", name="uq_seller_carrier_operation_key"),
        UniqueConstraint("provider_operation_ref", name="uq_seller_carrier_operation_ref"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    shipment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("seller_shipments.id", ondelete="CASCADE"), nullable=False
    )
    seller_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sellers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    idempotency_key: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(24), nullable=False, default="LOCAL_TEST")
    provider_operation_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING_PROVIDER")
    tracking_number: Mapped[str | None] = mapped_column(String(100), unique=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(String(100))
    shipment: Mapped["SellerShipment"] = relationship(back_populates="carrier_operation")
