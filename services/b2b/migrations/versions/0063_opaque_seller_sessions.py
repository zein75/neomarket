"""Add opaque server-side seller sessions for the BFF."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0063_opaque_seller_sessions"
down_revision = "0062_tax_labels_export_fence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "seller_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seller_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_session_version", sa.Integer(), nullable=False),
        sa.Column("seller_session_version", sa.Integer(), nullable=False),
        sa.Column("refresh_family_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("refresh_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("device_label", sa.String(length=160), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["seller_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_seller_sessions_token_hash"),
    )
    op.create_index(
        "ix_seller_sessions_user_active",
        "seller_sessions",
        ["user_id", "revoked_at", "expires_at"],
    )
    op.create_index(
        "ix_seller_sessions_seller_active",
        "seller_sessions",
        ["seller_id", "revoked_at", "expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_seller_sessions_seller_active", table_name="seller_sessions")
    op.drop_index("ix_seller_sessions_user_active", table_name="seller_sessions")
    op.drop_table("seller_sessions")
