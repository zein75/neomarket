"""add consumer inbox receipts for event deduplication"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0025_inbox_events"
down_revision: Union[str, None] = "0024_outbox_retry_leases"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    op.create_table(
        "inbox_events",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("producer", sa.String(32), nullable=False),
        sa.Column("event_id", uuid, nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="RECEIVED"),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("producer", "event_id", name="uq_inbox_producer_event"),
    )


def downgrade() -> None:
    op.drop_table("inbox_events")
