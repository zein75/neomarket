"""Add integer product revisions for atomic optimistic concurrency."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0031_product_revision"
down_revision: Union[str, None] = "0030_product_create_op"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
    )
    op.alter_column("products", "revision", server_default=None)


def downgrade() -> None:
    op.drop_column("products", "revision")
