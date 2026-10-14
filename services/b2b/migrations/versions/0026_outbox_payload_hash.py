"""store immutable outbox payload hashes"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0026_outbox_payload_hash"
down_revision: Union[str, None] = "0025_inbox_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("outbox_events", sa.Column("payload_sha256", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("outbox_events", "payload_sha256")
