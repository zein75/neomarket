"""Persist the checkout delivery method on the immutable order snapshot."""

from alembic import op
import sqlalchemy as sa

revision = "0031_order_delivery_method"
down_revision = "0030_checkout_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("delivery_method", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "delivery_method")
