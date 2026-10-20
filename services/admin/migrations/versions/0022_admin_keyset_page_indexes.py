"""Add indexes for Admin keyset-paginated registries."""

from alembic import op


revision = "0022_admin_keyset_page_indexes"
down_revision = "0021_admin_runtime_db_role"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_index("ix_staff_principals_created_id", "staff_principals", ["created_at", "id"])
    op.create_index("ix_admin_operations_created_id", "admin_operations", ["created_at", "id"])
    op.create_index("ix_moderation_outbox_created_id", "moderation_outbox_events", ["created_at", "id"])
    op.create_index("ix_blocking_reasons_created_id", "blocking_reasons", ["created_at", "id"])
    op.execute(
        "CREATE INDEX ix_admin_policies_page "
        "ON admin_policies (code ASC, version DESC, id ASC)"
    )


def downgrade() -> None:
    op.drop_index("ix_admin_policies_page", table_name="admin_policies")
    op.drop_index("ix_blocking_reasons_created_id", table_name="blocking_reasons")
    op.drop_index("ix_moderation_outbox_created_id", table_name="moderation_outbox_events")
    op.drop_index("ix_admin_operations_created_id", table_name="admin_operations")
    op.drop_index("ix_staff_principals_created_id", table_name="staff_principals")
