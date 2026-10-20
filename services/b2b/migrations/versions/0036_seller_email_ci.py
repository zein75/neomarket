"""Enforce case-insensitive seller email uniqueness."""

from alembic import op
import sqlalchemy as sa


revision = "0036_seller_email_ci"
down_revision = "0035_seller_session_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_sellers_email_lower",
        "sellers",
        [sa.text("lower(email)")],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_sellers_email_lower", table_name="sellers")
