import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ModerationSnapshot(Base):
    """Immutable Admin-side copy of one B2B product revision event payload."""

    __tablename__ = "moderation_snapshots"
    __table_args__ = (
        UniqueConstraint("ticket_id", "revision", name="uq_moderation_snapshot_ticket_revision"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("moderation_cards.id", ondelete="RESTRICT"), nullable=False
    )
    revision: Mapped[int] = mapped_column(nullable=False)
    policy_version: Mapped[int | None] = mapped_column(nullable=True)
    # B2B's digest is forwarded unchanged for revision CAS. content_hash
    # independently protects the Admin-side serialized snapshot at rest.
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    media_refs: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
