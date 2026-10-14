"""add on_hand as an expand/backfill step for the stock migration"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0020_sku_on_hand_expand"
down_revision: Union[str, None] = "0019_inventory_lifecycle_ledger"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("skus", sa.Column("on_hand", sa.Integer(), nullable=True))
    op.execute("UPDATE skus SET on_hand = stock WHERE on_hand IS NULL")
    op.create_check_constraint(
        "ck_skus_on_hand_nonnegative", "skus", "on_hand IS NULL OR on_hand >= 0"
    )


def downgrade() -> None:
    op.drop_constraint("ck_skus_on_hand_nonnegative", "skus", type_="check")
    op.drop_column("skus", "on_hand")
