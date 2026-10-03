"""add delivering order status

Revision ID: 0004_order_delivering_status
Revises: 0003_order_checkout_contract
Create Date: 2026-07-20

"""
from typing import Sequence, Union

from alembic import op


revision: str = "0004_order_delivering_status"
down_revision: Union[str, None] = "0003_order_checkout_contract"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE orderstatus ADD VALUE IF NOT EXISTS 'DELIVERING'")


def downgrade() -> None:
    pass
