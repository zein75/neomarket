"""Add seller-scoped inventory import previews and commit receipts."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0044_inventory_import_jobs"
down_revision = "0043_product_published_snapshot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    op.create_table(
        "inventory_import_jobs",
        sa.Column("id", uuid, nullable=False),
        sa.Column("seller_id", uuid, nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=16), server_default="PREVIEWED", nullable=False),
        sa.Column("commit_key", sa.String(length=128), nullable=True),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("state IN ('PREVIEWED', 'COMMITTED', 'PARTIAL')", name="ck_inventory_import_state"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("seller_id", "idempotency_key", name="uq_inventory_import_seller_key"),
        sa.UniqueConstraint("seller_id", "commit_key", name="uq_inventory_import_seller_commit_key"),
    )
    op.create_index("ix_inventory_import_jobs_seller_id", "inventory_import_jobs", ["seller_id"])
    op.create_table(
        "inventory_import_rows",
        sa.Column("id", uuid, nullable=False),
        sa.Column("job_id", uuid, nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("seller_article", sa.String(length=128), nullable=False),
        sa.Column("target_on_hand", sa.BigInteger(), nullable=False),
        sa.Column("sku_id", uuid, nullable=True),
        sa.Column("before_on_hand", sa.BigInteger(), nullable=True),
        sa.Column("expected_revision", sa.Integer(), nullable=True),
        sa.Column("delta", sa.BigInteger(), nullable=True),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("error_code", sa.String(length=40), nullable=True),
        sa.Column("error_message", sa.String(length=255), nullable=True),
        sa.Column("result_on_hand", sa.BigInteger(), nullable=True),
        sa.CheckConstraint("row_number >= 1", name="ck_inventory_import_row_number_positive"),
        sa.CheckConstraint("target_on_hand >= 0", name="ck_inventory_import_target_nonnegative"),
        sa.ForeignKeyConstraint(["job_id"], ["inventory_import_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "row_number", name="uq_inventory_import_rows_job_row"),
    )
    op.create_index("ix_inventory_import_rows_job_id", "inventory_import_rows", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_inventory_import_rows_job_id", table_name="inventory_import_rows")
    op.drop_table("inventory_import_rows")
    op.drop_index("ix_inventory_import_jobs_seller_id", table_name="inventory_import_jobs")
    op.drop_table("inventory_import_jobs")
