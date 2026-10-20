import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, JSON, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class Category(Base, TimestampMixin):
    __tablename__ = "categories"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    code: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
        unique=True,
        default=lambda context: context.get_current_parameters()["slug"],
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    labels: Mapped[dict[str, str]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        default=dict,
        server_default=text("'{}'"),
        nullable=False,
    )
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("categories.id"),
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), default="ACTIVE", server_default="ACTIVE", nullable=False
    )
    sort_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    seo_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    image_media_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    schema_version: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    attribute_rules: Mapped[list[dict[str, object]]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        default=list,
        server_default=text("'[]'"),
        nullable=False,
    )
    attribute_schema: Mapped[list[dict[str, object]]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), default=list, nullable=False
    )
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
