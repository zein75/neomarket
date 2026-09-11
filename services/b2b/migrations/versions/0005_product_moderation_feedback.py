"""product moderation feedback

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("products", sa.Column("blocking_reason", sa.JSON(), nullable=True))
    op.add_column(
        "products",
        sa.Column("field_reports", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )
    op.alter_column("products", "field_reports", server_default=None)


def downgrade() -> None:
    op.drop_column("products", "field_reports")
    op.drop_column("products", "blocking_reason")
