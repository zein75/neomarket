"""Persist complete seller draft variant data and support batch operations."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0040_product_draft_variant_batch"
down_revision = "0039_seller_tenant_switch_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("skus", "price", type_=sa.BigInteger(), existing_type=sa.Integer(), existing_nullable=False)
    op.alter_column("skus", "stock", type_=sa.BigInteger(), existing_type=sa.Integer(), existing_nullable=False)
    op.alter_column("skus", "on_hand", type_=sa.BigInteger(), existing_type=sa.Integer(), existing_nullable=True)
    op.alter_column("skus", "reserved_quantity", type_=sa.BigInteger(), existing_type=sa.Integer(), existing_nullable=False)
    op.add_column("skus", sa.Column("seller_article", sa.String(length=128), nullable=True))
    op.add_column(
        "skus",
        sa.Column("currency", sa.String(length=3), server_default="RUB", nullable=False),
    )
    op.add_column(
        "skus",
        sa.Column("options", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=False),
    )
    op.create_index(
        "uq_skus_product_seller_article_ci",
        "skus",
        ["product_id", sa.text("lower(seller_article)")],
        unique=True,
        postgresql_where=sa.text("seller_article IS NOT NULL"),
    )
    op.add_column(
        "seller_product_creations",
        sa.Column("operation_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.execute("UPDATE seller_product_creations SET operation_id = product_id WHERE operation_id IS NULL")
    op.alter_column("seller_product_creations", "operation_id", nullable=False)
    op.create_unique_constraint(
        "uq_seller_product_creations_operation_id",
        "seller_product_creations",
        ["operation_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_seller_product_creations_operation_id",
        "seller_product_creations",
        type_="unique",
    )
    op.drop_column("seller_product_creations", "operation_id")
    op.drop_index("uq_skus_product_seller_article_ci", table_name="skus")
    op.drop_column("skus", "options")
    op.drop_column("skus", "currency")
    op.drop_column("skus", "seller_article")
    op.alter_column("skus", "reserved_quantity", type_=sa.Integer(), existing_type=sa.BigInteger(), existing_nullable=False)
    op.alter_column("skus", "on_hand", type_=sa.Integer(), existing_type=sa.BigInteger(), existing_nullable=True)
    op.alter_column("skus", "stock", type_=sa.Integer(), existing_type=sa.BigInteger(), existing_nullable=False)
    op.alter_column("skus", "price", type_=sa.Integer(), existing_type=sa.BigInteger(), existing_nullable=False)
