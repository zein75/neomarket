"""Persist bounded asynchronous seller inventory exports."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0059_seller_inventory_exports"
down_revision = "0058_product_category_fk"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "seller_inventory_exports",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seller_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("filters", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("artifact_removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("failure_code", sa.String(length=40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "state IN ('PENDING', 'PROCESSING', 'READY', 'FAILED', 'EXPIRED')",
            name="ck_seller_inventory_exports_state",
        ),
        sa.CheckConstraint("row_count >= 0", name="ck_seller_inventory_exports_row_count"),
        sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("seller_id", "idempotency_key", name="uq_seller_inventory_exports_seller_key"),
    )
    op.create_index(
        "ix_seller_inventory_exports_worker",
        "seller_inventory_exports",
        ["state", "lease_expires_at", "created_at"],
    )
    op.create_index(
        "ix_seller_inventory_exports_expiry",
        "seller_inventory_exports",
        ["state", "expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_seller_inventory_exports_expiry", table_name="seller_inventory_exports")
    op.drop_index("ix_seller_inventory_exports_worker", table_name="seller_inventory_exports")
    op.drop_table("seller_inventory_exports")
