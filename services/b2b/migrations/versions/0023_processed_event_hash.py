"""store moderation event payload hashes for replay integrity"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0023_processed_event_hash"
down_revision: Union[str, None] = "0022_outbox_event_metadata"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("processed_events", sa.Column("payload_hash", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("processed_events", "payload_hash")
