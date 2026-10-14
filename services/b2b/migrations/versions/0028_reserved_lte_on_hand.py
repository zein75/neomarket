"""Enforce reservations against the inventory quantity used at runtime."""

from alembic import op


revision = "0028_reserved_lte_on_hand"
down_revision = "0027_catalog_filter_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_skus_reserved_lte_on_hand",
        "skus",
        "reserved_quantity <= COALESCE(on_hand, stock)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_skus_reserved_lte_on_hand", "skus", type_="check")
