"""Index the unfiltered moderation queue in its stable keyset order."""

from alembic import op
import sqlalchemy as sa


revision = "0029_admin_moderation_queue_order"
down_revision = "0028_admin_casework_input_constraints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Build without blocking moderation writes during deployment.
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_admin_moderation_queue_order",
            "moderation_cards",
            [
                sa.text("queue_priority DESC"),
                sa.text("created_at ASC"),
                sa.text("id ASC"),
            ],
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_admin_moderation_queue_order",
            table_name="moderation_cards",
            postgresql_concurrently=True,
        )
