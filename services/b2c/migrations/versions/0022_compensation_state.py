"""Make checkout compensation safe across an unreserve/commit crash.

Revision ID: 0022_compensation_state
Revises: 0021_compensation_tombstone
"""

from alembic import op
import sqlalchemy as sa


revision = "0022_compensation_state"
down_revision = "0021_compensation_tombstone"
branch_labels = None
depends_on = None


compensation_state = sa.Enum(
    "PENDING",
    "COMPENSATING",
    "COMPENSATED",
    name="checkout_compensation_state",
)


def upgrade() -> None:
    bind = op.get_bind()
    compensation_state.create(bind, checkfirst=True)
    op.add_column(
        "pending_reservation_compensations",
        sa.Column(
            "compensation_state",
            compensation_state,
            nullable=False,
            server_default="PENDING",
        ),
    )
    # Existing tombstones remain terminal; all other old rows are safe to
    # retry from PENDING because no pre-unreserve state existed before this
    # migration.
    op.execute(
        "UPDATE pending_reservation_compensations "
        "SET compensation_state = 'COMPENSATED' "
        "WHERE compensated_at IS NOT NULL"
    )
    op.alter_column(
        "pending_reservation_compensations",
        "compensation_state",
        server_default=None,
    )


def downgrade() -> None:
    op.drop_column("pending_reservation_compensations", "compensation_state")
    compensation_state.drop(op.get_bind(), checkfirst=True)
