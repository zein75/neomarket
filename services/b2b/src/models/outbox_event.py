import uuid
from typing import Any

from datetime import datetime

from sqlalchemy import DateTime, JSON, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class OutboxEvent(Base, TimestampMixin):
    __tablename__ = "outbox_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), unique=True, nullable=True
    )
    schema_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    destination: Mapped[str] = mapped_column(String(32), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(
        String(128), nullable=False, unique=True
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    payload_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    aggregate_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    aggregate_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    aggregate_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(16), default="PENDING", nullable=False)
    attempts: Mapped[int] = mapped_column(default=0, nullable=False)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_owner: Mapped[str | None] = mapped_column(String(128))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(500))
