"""add event envelope metadata to the outbox"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0022_outbox_event_metadata"
down_revision: Union[str, None] = "0021_stock_adjustments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    op.add_column("outbox_events", sa.Column("event_id", uuid, nullable=True))
    op.add_column("outbox_events", sa.Column("schema_version", sa.Integer(), nullable=True))
    op.add_column("outbox_events", sa.Column("aggregate_type", sa.String(32), nullable=True))
    op.add_column("outbox_events", sa.Column("aggregate_id", uuid, nullable=True))
    op.add_column("outbox_events", sa.Column("aggregate_version", sa.Integer(), nullable=True))
    op.add_column("outbox_events", sa.Column("correlation_id", uuid, nullable=True))
    op.create_unique_constraint("uq_outbox_events_event_id", "outbox_events", ["event_id"])


def downgrade() -> None:
    op.drop_constraint("uq_outbox_events_event_id", "outbox_events", type_="unique")
    for column in ("correlation_id", "aggregate_version", "aggregate_id", "aggregate_type", "schema_version", "event_id"):
        op.drop_column("outbox_events", column)
