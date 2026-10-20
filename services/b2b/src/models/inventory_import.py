import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin


class InventoryImportJob(Base, TimestampMixin):
    __tablename__ = "inventory_import_jobs"
    __table_args__ = (
        UniqueConstraint("seller_id", "idempotency_key", name="uq_inventory_import_seller_key"),
        UniqueConstraint("seller_id", "commit_key", name="uq_inventory_import_seller_commit_key"),
        CheckConstraint("state IN ('PREVIEWED', 'COMMITTED', 'PARTIAL')", name="ck_inventory_import_state"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    seller_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="PREVIEWED")
    commit_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rows: Mapped[list["InventoryImportRow"]] = relationship(
        back_populates="job", cascade="all, delete-orphan", order_by="InventoryImportRow.row_number", lazy="selectin"
    )


class InventoryImportRow(Base):
    __tablename__ = "inventory_import_rows"
    __table_args__ = (
        UniqueConstraint("job_id", "row_number", name="uq_inventory_import_rows_job_row"),
        CheckConstraint("row_number >= 1", name="ck_inventory_import_row_number_positive"),
        CheckConstraint("target_on_hand >= 0", name="ck_inventory_import_target_nonnegative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inventory_import_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    seller_article: Mapped[str] = mapped_column(String(128), nullable=False)
    target_on_hand: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sku_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    before_on_hand: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    expected_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    delta: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(255), nullable=True)
    result_on_hand: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    job: Mapped[InventoryImportJob] = relationship(back_populates="rows")
