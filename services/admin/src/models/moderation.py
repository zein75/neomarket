import enum
import uuid

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin


class ModerationStatus(enum.Enum):
    CREATED = "CREATED"
    PENDING = "PENDING"
    IN_REVIEW = "IN_REVIEW"
    MODERATED = "MODERATED"
    BLOCKED = "BLOCKED"
    HARD_BLOCKED = "HARD_BLOCKED"
    EDITED = "EDITED"


class BlockingReason(Base, TimestampMixin):
    __tablename__ = "blocking_reasons"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    hard_block: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class ModerationCard(Base, TimestampMixin):
    __tablename__ = "moderation_cards"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    seller_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    kind: Mapped[str] = mapped_column(String(32), default="PRODUCT", nullable=False)
    queue_priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    moderator_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
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
