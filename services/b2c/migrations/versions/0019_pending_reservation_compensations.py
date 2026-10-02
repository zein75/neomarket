"""Add durable compensation jobs for failed checkout persistence.

Revision ID: 0019_reserve_compensation
Revises: 0018_order_timestamps_tz
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0019_reserve_compensation"
down_revision = "0018_order_timestamps_tz"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pending_reservation_compensations",
        sa.Column("order_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("items", sa.JSON(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("pending_reservation_compensations")
