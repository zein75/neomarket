import uuid
from datetime import datetime, timezone

from typing import Any

from sqlalchemy import JSON, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class ReservationOperation(Base, TimestampMixin):
    __tablename__ = "reservation_operations"

    idempotency_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    response: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    def is_expired(self, ttl_seconds: int = 3600) -> bool:
        created_at = self.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - created_at).total_seconds() >= ttl_seconds
