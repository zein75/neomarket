"""persist the first reservation response for idempotent retries"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0016_reservation_response"
down_revision: Union[str, None] = "0015_unreserve_idempotency"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("reservation_operations", sa.Column("response", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("reservation_operations", "response")
