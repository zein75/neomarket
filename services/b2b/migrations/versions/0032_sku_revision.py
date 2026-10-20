"""Add integer SKU revisions for atomic optimistic concurrency."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0032_sku_rev"
down_revision: Union[str, None] = "0031_product_revision"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "skus", sa.Column("revision", sa.Integer(), nullable=False, server_default="1")
    )
    op.alter_column("skus", "revision", server_default=None)


def downgrade() -> None:
    op.drop_column("skus", "revision")
