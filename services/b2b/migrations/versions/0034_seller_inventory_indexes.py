"""Add indexes for bounded seller inventory pagination."""

from alembic import op


revision = "0034_seller_inventory_indexes"
down_revision = "0033_seller_orders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_products_seller_deleted_id",
        "products",
        ["seller_id", "deleted", "id"],
    )
    op.create_index("ix_skus_product_id_id", "skus", ["product_id", "id"])


def downgrade() -> None:
    op.drop_index("ix_skus_product_id_id", table_name="skus")
    op.drop_index("ix_products_seller_deleted_id", table_name="products")
