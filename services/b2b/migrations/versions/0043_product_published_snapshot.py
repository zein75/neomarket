"""Persist immutable approved product snapshots."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0043_product_published_snapshot"
down_revision = "0042_category_attribute_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("products", sa.Column("published_revision", sa.Integer(), nullable=True))
    op.add_column(
        "products",
        sa.Column("published_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_table(
        "product_versions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seller_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("is_published", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("product_id", "revision", name="uq_product_versions_product_revision"),
    )
    op.create_index("ix_product_versions_product_id", "product_versions", ["product_id"])
    op.create_index("ix_product_versions_seller_id", "product_versions", ["seller_id"])


def downgrade() -> None:
    op.drop_index("ix_product_versions_seller_id", table_name="product_versions")
    op.drop_index("ix_product_versions_product_id", table_name="product_versions")
    op.drop_table("product_versions")
    op.drop_column("products", "published_snapshot")
    op.drop_column("products", "published_revision")
