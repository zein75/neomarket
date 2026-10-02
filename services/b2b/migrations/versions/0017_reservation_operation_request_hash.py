"""bind reserve idempotency keys to the original request"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0017_reserve_request_hash"
down_revision: Union[str, None] = "0016_reservation_response"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Historical rows predate request fingerprints. They expire after one
    # hour; the service rejects their reuse rather than replaying a request it
    # cannot prove is identical.
    op.add_column(
        "reservation_operations",
        sa.Column("request_hash", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("reservation_operations", "request_hash")
