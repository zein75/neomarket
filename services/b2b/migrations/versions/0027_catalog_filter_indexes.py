"""Add indexes supporting public catalog filtering."""

from alembic import op


revision = "0027_catalog_filter_indexes"
down_revision = "0026_outbox_payload_hash"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_products_public_catalog",
        "products",
        ["status", "deleted", "category_id", "seller_id", "created_at"],
    )
    op.create_index(
        "ix_skus_catalog_stock",
        "skus",
        ["product_id", "is_active", "on_hand", "reserved_quantity", "price"],
    )


def downgrade() -> None:
    op.drop_index("ix_skus_catalog_stock", table_name="skus")
    op.drop_index("ix_products_public_catalog", table_name="products")
