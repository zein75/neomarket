"""make cancellation timestamps timezone-aware

Revision ID: 0018_order_timestamps_tz
Revises: 0017_cancel_retry
"""

from alembic import op
import sqlalchemy as sa

revision = "0018_order_timestamps_tz"
down_revision = "0017_cancel_retry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table, column in (("orders", "cancelled_at"), ("orders", "cancel_retry_at"), ("order_status_history", "changed_at")):
        op.alter_column(table, column, type_=sa.DateTime(timezone=True), postgresql_using=f"{column} AT TIME ZONE 'UTC'")


def downgrade() -> None:
    for table, column in (("orders", "cancelled_at"), ("orders", "cancel_retry_at"), ("order_status_history", "changed_at")):
        op.alter_column(table, column, type_=sa.DateTime(), postgresql_using=f"{column} AT TIME ZONE 'UTC'")
