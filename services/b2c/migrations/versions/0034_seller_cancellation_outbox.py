"""Allow more than one lifecycle event per seller allocation."""

from alembic import op


revision = "0034_seller_cancel_outbox"
down_revision = "0033_seller_order_outbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_seller_order_outbox_seller_order", "seller_order_outbox", type_="unique"
    )


def downgrade() -> None:
    op.create_unique_constraint(
        "uq_seller_order_outbox_seller_order", "seller_order_outbox", ["seller_order_id"]
    )
