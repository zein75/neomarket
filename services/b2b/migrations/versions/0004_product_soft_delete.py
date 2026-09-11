"""product soft delete

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column("deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("products", "deleted", server_default=None)


def downgrade() -> None:
    op.drop_column("products", "deleted")
