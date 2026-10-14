"""enforce non-negative SKU inventory invariants"""

from typing import Sequence, Union

from alembic import op


revision: str = "0018_sku_inventory_constraints"
down_revision: Union[str, None] = "0017_reserve_request_hash"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_skus_price_nonnegative", "skus", "price >= 0"
    )
    op.create_check_constraint(
        "ck_skus_stock_nonnegative", "skus", "stock >= 0"
    )
    op.create_check_constraint(
        "ck_skus_reserved_nonnegative", "skus", "reserved_quantity >= 0"
    )
    op.create_check_constraint(
        "ck_skus_reserved_lte_stock", "skus", "reserved_quantity <= stock"
    )


def downgrade() -> None:
    op.drop_constraint("ck_skus_reserved_lte_stock", "skus", type_="check")
    op.drop_constraint("ck_skus_reserved_nonnegative", "skus", type_="check")
    op.drop_constraint("ck_skus_stock_nonnegative", "skus", type_="check")
    op.drop_constraint("ck_skus_price_nonnegative", "skus", type_="check")
