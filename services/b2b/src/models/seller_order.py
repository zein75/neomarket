import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin

if TYPE_CHECKING:
    from .seller_shipment import SellerShipment


class SellerOrder(Base, TimestampMixin):
    """Seller-owned allocation projection; excludes buyer identity and delivery PII."""

    __tablename__ = "seller_orders"
    __table_args__ = (
        UniqueConstraint("seller_id", "buyer_order_id", name="uq_seller_orders_tenant_buyer_order"),
        CheckConstraint("total_minor >= 0", name="ck_seller_orders_total_nonnegative"),
        CheckConstraint("revision >= 1", name="ck_seller_orders_revision_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    buyer_order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    seller_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sellers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="CREATED")
    total_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    allocated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    seller_accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    items: Mapped[list["SellerOrderItem"]] = relationship(
        back_populates="seller_order", cascade="all, delete-orphan", lazy="selectin"
    )
    shipments: Mapped[list["SellerShipment"]] = relationship(
        back_populates="seller_order", cascade="all, delete-orphan", lazy="selectin"
    )


class SellerOrderItem(Base):
    __tablename__ = "seller_order_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_seller_order_items_quantity_positive"),
        CheckConstraint("unit_price_minor >= 0", name="ck_seller_order_items_price_nonnegative"),
        CheckConstraint("line_total_minor >= 0", name="ck_seller_order_items_total_nonnegative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    seller_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("seller_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sku_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    product_title: Mapped[str] = mapped_column(String(255), nullable=False)
    sku_name: Mapped[str] = mapped_column(String(255), nullable=False)
    quantity: Mapped[int] = mapped_column(nullable=False)
    unit_price_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    line_total_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)

    seller_order: Mapped[SellerOrder] = relationship(back_populates="items")
