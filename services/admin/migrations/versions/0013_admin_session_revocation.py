"""Add per-token and staff-wide Admin session revocation."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0013_admin_session_revocation"
down_revision = "0012_admin_appeals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("staff_principals", sa.Column("sessions_revoked_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "revoked_admin_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("principal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["principal_id"], ["staff_principals.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_revoked_admin_sessions_expiry", "revoked_admin_sessions", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_revoked_admin_sessions_expiry", table_name="revoked_admin_sessions")
    op.drop_table("revoked_admin_sessions")
    op.drop_column("staff_principals", "sessions_revoked_at")
