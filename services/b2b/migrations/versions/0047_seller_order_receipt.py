"""Persist seller receipt confirmation for an allocation."""

from alembic import op
import sqlalchemy as sa


revision = "0047_order_receipt"
down_revision = "0046_media_complete_queue"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("seller_orders", sa.Column("seller_accepted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("seller_orders", "seller_accepted_at")
