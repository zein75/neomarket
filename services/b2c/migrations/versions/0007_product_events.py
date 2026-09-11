"""product events

Revision ID: 0007_product_events
Revises: 0006_home_collections
Create Date: 2026-07-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0007_product_events"
down_revision: Union[str, None] = "0006_home_collections"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "cart_items",
        sa.Column("unavailable_reason", sa.String(length=50), nullable=True),
    )
    op.create_table(
        "processed_b2b_events",
        sa.Column("idempotency_key", sa.UUID(), nullable=False),
        sa.Column("event", sa.String(length=50), nullable=False),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("idempotency_key"),
    )


def downgrade() -> None:
    op.drop_table("processed_b2b_events")
    op.drop_column("cart_items", "unavailable_reason")
