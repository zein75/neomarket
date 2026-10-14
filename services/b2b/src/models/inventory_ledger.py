import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class InventoryLedger(Base):
    """Append-only inventory delta record used for reconciliation."""

    __tablename__ = "inventory_ledger"

    entry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True, nullable=False)
    order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    sku_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("skus.id", ondelete="RESTRICT"), nullable=False
    )
    delta_on_hand: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    delta_reserved: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(128))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(128))
