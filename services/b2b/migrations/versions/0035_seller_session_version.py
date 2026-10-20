"""Add seller-wide session revocation version."""

from alembic import op
import sqlalchemy as sa


revision = "0035_seller_session_version"
down_revision = "0034_seller_inventory_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sellers",
        sa.Column("session_version", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("sellers", "session_version")
