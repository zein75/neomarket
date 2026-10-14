"""add audited seller stock adjustments"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0021_stock_adjustments"
down_revision: Union[str, None] = "0020_sku_on_hand_expand"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    op.create_table(
        "stock_adjustments",
        sa.Column("adjustment_id", uuid, primary_key=True),
        sa.Column("sku_id", uuid, nullable=False),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(64), nullable=False),
        sa.Column("seller_id", uuid, nullable=False),
        sa.Column("idempotency_key", sa.String(128), unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["sku_id"], ["skus.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("delta <> 0", name="ck_stock_adjustments_delta_nonzero"),
    )


def downgrade() -> None:
    op.drop_table("stock_adjustments")
