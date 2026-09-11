import uuid

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class ReservationOperation(Base, TimestampMixin):
    __tablename__ = "reservation_operations"

    idempotency_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
