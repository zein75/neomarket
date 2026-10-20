"""Index the stable priority-first complaint queue order."""

from alembic import op
import sqlalchemy as sa


revision = "0027_admin_complaint_queue_order"
down_revision = "0026_admin_complaint_deadline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_admin_complaints_queue_order",
            "admin_complaints",
            [sa.text("priority DESC"), sa.text("created_at ASC"), sa.text("id ASC")],
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_admin_complaints_queue_order",
            table_name="admin_complaints",
            postgresql_concurrently=True,
        )
