"""add order request fingerprint

Revision ID: 0010_order_request_fingerprint
Revises: 0009_product_subscriptions
Create Date: 2026-07-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0010_order_request_fingerprint"
down_revision: Union[str, None] = "0009_product_subscriptions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("request_fingerprint", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("orders", "request_fingerprint")
