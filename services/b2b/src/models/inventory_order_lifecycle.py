import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, JSON, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class InventoryOrderLifecycle(Base, TimestampMixin):
    """Durable, non-expiring state machine for one inventory order."""

    __tablename__ = "inventory_order_lifecycle"

    order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="NEW")
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    reserved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str | None] = mapped_column(String(64))
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    __table_args__ = (
        CheckConstraint(
            "state IN ('NEW', 'RESERVED', 'CANCELLED', 'FULFILLED')",
            name="ck_inventory_lifecycle_state",
        ),
        CheckConstraint("version >= 0", name="ck_inventory_lifecycle_version"),
    )


class ReservationLine(Base):
    """Immutable identity of an order's requested SKU quantities."""

    __tablename__ = "reservation_lines"

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("inventory_order_lifecycle.order_id", ondelete="CASCADE"),
        primary_key=True,
    )
    sku_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("skus.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    quantity: Mapped[int] = mapped_column(nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fulfilled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_reservation_lines_quantity"),
        CheckConstraint(
            "state IN ('ACTIVE', 'RELEASED', 'FULFILLED')",
            name="ck_reservation_lines_state",
        ),
    )
