"""add durable outbox retry and lease metadata"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0024_outbox_retry_leases"
down_revision: Union[str, None] = "0023_processed_event_hash"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("outbox_events", sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("outbox_events", sa.Column("lease_owner", sa.String(128), nullable=True))
    op.add_column("outbox_events", sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column("outbox_events", sa.Column("last_error", sa.String(500), nullable=True))


def downgrade() -> None:
    for column in ("last_error", "lease_until", "lease_owner", "next_retry_at"):
        op.drop_column("outbox_events", column)
