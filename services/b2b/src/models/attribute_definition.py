import uuid

from sqlalchemy import Boolean, CheckConstraint, Index, Integer, JSON, String, text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class AttributeDefinition(Base, TimestampMixin):
    __tablename__ = "attribute_definitions"
    __table_args__ = (
        CheckConstraint(
            "data_type IN ('string','integer','decimal','boolean','enum','multi_enum','date','reference')",
            name="ck_attribute_definitions_data_type",
        ),
        CheckConstraint("version >= 1", name="ck_attribute_definitions_version_positive"),
        CheckConstraint("status IN ('ACTIVE','HIDDEN','ARCHIVED')", name="ck_attribute_definitions_status"),
        Index("uq_attribute_definitions_code_ci", func.lower(text("code")), unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    data_type: Mapped[str] = mapped_column(String(16), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(80), nullable=True)
    constraints: Mapped[dict[str, object]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False, default=dict, server_default=text("'{}'")
    )
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    filterable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    searchable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    comparable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    variant_dimension: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    pii: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE", server_default="ACTIVE")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
