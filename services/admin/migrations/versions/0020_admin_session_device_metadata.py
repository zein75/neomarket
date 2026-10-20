"""Store a bounded user-agent label for Admin session inventory."""

from alembic import op
import sqlalchemy as sa


revision = "0020_session_device_meta"
down_revision = "0019_admin_step_up_mfa"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("admin_web_sessions", sa.Column("user_agent", sa.String(length=512), nullable=True))


def downgrade() -> None:
    op.drop_column("admin_web_sessions", "user_agent")
