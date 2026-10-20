"""Add opaque Admin BFF sessions with idle and absolute expiry."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0017_admin_web_sessions"
down_revision = "0016_audit_export_artifacts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_web_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("principal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("csrf_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idle_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("absolute_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["principal_id"], ["staff_principals.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("idle_expires_at <= absolute_expires_at", name="ck_admin_web_session_idle_before_absolute"),
        sa.CheckConstraint("last_seen_at <= absolute_expires_at", name="ck_admin_web_session_seen_before_absolute"),
    )
    op.create_index("ix_admin_web_sessions_principal", "admin_web_sessions", ["principal_id", "revoked_at"])
    op.create_index("ix_admin_web_sessions_expiry", "admin_web_sessions", ["idle_expires_at", "absolute_expires_at"])


def downgrade() -> None:
    op.drop_index("ix_admin_web_sessions_expiry", table_name="admin_web_sessions")
    op.drop_index("ix_admin_web_sessions_principal", table_name="admin_web_sessions")
    op.drop_table("admin_web_sessions")
