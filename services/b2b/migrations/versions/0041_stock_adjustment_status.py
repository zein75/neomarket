"""Store ledger reference for stock adjustment status recovery."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0041_stock_adjustment_status"
down_revision = "0040_product_draft_variant_batch"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "stock_adjustments",
        sa.Column("ledger_entry_id", postgresql.UUID(as_uuid=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("stock_adjustments", "ledger_entry_id")
