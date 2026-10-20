import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ModerationDecisionReceipt(Base):
    """Durable idempotency receipt for a version-bound moderation command."""

    __tablename__ = "moderation_decision_receipts"
    __table_args__ = (
        UniqueConstraint(
            "actor_id", "idempotency_key", name="uq_moderation_decision_actor_key"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("moderation_cards.id"), nullable=False
    )
    actor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    product_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    snapshot_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    policy_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason_codes: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    passed_rules: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    field_reports: Mapped[list[dict[str, object]] | None] = mapped_column(JSON, nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
