import uuid

from sqlalchemy import ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import mapped_column, Mapped

from .base import Base, TimestampMixin


class Reservation(Base, TimestampMixin):
    __tablename__ = "reservations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    sku_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("skus.id", ondelete="CASCADE"),
        nullable=False,
    )
    order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
