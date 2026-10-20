import enum
import uuid

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin


class ModerationStatus(enum.Enum):
    CREATED = "CREATED"
    PENDING = "PENDING"
    IN_REVIEW = "IN_REVIEW"
    DECISION_PENDING = "DECISION_PENDING"
    WAITING_SELLER = "WAITING_SELLER"
    ESCALATED = "ESCALATED"
    STALE = "STALE"
    CANCELLED = "CANCELLED"
    MODERATED = "MODERATED"
    BLOCKED = "BLOCKED"
    HARD_BLOCKED = "HARD_BLOCKED"
    EDITED = "EDITED"


class BlockingReason(Base, TimestampMixin):
    __tablename__ = "blocking_reasons"
    __table_args__ = (Index("ix_blocking_reasons_created_id", "created_at", "id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity: Mapped[str] = mapped_column(String(24), default="REJECT", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    hard_block: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class ModerationCard(Base, TimestampMixin):
    __tablename__ = "moderation_cards"
    __table_args__ = (
        Index(
            "ix_admin_moderation_queue_order",
            text("queue_priority DESC"),
            text("created_at ASC"),
            text("id ASC"),
        ),
        UniqueConstraint(
            "product_id",
            "submitted_revision",
            "kind",
            name="uq_moderation_product_revision_kind",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    seller_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(32), default="CREATE", nullable=False)
    queue_priority: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    moderator_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    # Historical cards are intentionally nullable until reconciled against an
    # authoritative immutable B2B revision. They cannot be decided while null.
    submitted_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    snapshot_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    lease_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[object | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    fencing_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[ModerationStatus] = mapped_column(
        Enum(ModerationStatus), default=ModerationStatus.CREATED, nullable=False
    )

    skus: Mapped[list["ModerationSKU"]] = relationship(
        "ModerationSKU",
        back_populates="card",
        cascade="all, delete-orphan",
    )


class ModerationSKU(Base, TimestampMixin):
    __tablename__ = "moderation_skus"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    card_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("moderation_cards.id", ondelete="CASCADE"),
        nullable=False,
    )
    sku_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(255), default="", nullable=False)

    card: Mapped[ModerationCard] = relationship("ModerationCard", back_populates="skus")
