"""Repair runtime schema introspection privileges for existing deployments."""

from alembic import op


revision = "0030_admin_runtime_schema_read"
down_revision = "0029_admin_moderation_queue_order"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The application verifies its migration head at /ready. Keep this
    # permission narrow; admin_runtime still cannot alter the schema.
    op.execute("GRANT SELECT ON TABLE alembic_version TO admin_runtime")


def downgrade() -> None:
    op.execute("REVOKE SELECT ON TABLE alembic_version FROM admin_runtime")
