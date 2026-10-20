"""Separate seller login identities and tenant memberships."""

from alembic import op
import sqlalchemy as sa


revision = "0038_seller_memberships"
down_revision = "0037_seller_email_verify"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "seller_users",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("session_version", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_seller_users_email_lower",
        "seller_users",
        [sa.text("lower(email)")],
        unique=True,
    )
    op.execute(
        "INSERT INTO seller_users (id, email, hashed_password, is_active, email_verified_at, session_version, created_at, updated_at) "
        "SELECT id, email, hashed_password, is_active, email_verified_at, session_version, created_at, updated_at FROM sellers"
    )

    op.create_table(
        "seller_memberships",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("seller_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["seller_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("seller_id", "user_id", name="uq_seller_memberships_seller_user"),
        sa.CheckConstraint(
            "role IN ('OWNER', 'MANAGER', 'CATALOG_EDITOR', 'WAREHOUSE_OPERATOR', 'SUPPORT', 'FINANCE', 'VIEWER')",
            name="ck_seller_memberships_role",
        ),
    )
    op.create_index("ix_seller_memberships_user_active", "seller_memberships", ["user_id", "active"])
    op.execute(
        "INSERT INTO seller_memberships (id, seller_id, user_id, role, active, created_at, updated_at) "
        "SELECT gen_random_uuid(), id, id, 'OWNER', true, created_at, updated_at FROM sellers"
    )

    op.create_table(
        "seller_invites",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("seller_id", sa.UUID(), nullable=False),
        sa.Column("invited_by_user_id", sa.UUID(), nullable=True),
        sa.Column("recipient_email_hash", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["invited_by_user_id"], ["seller_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
        sa.CheckConstraint(
            "role IN ('MANAGER', 'CATALOG_EDITOR', 'WAREHOUSE_OPERATOR', 'SUPPORT', 'FINANCE', 'VIEWER')",
            name="ck_seller_invites_role",
        ),
    )
    op.create_index("ix_seller_invites_expires_at", "seller_invites", ["expires_at"])
    op.create_index(
        "uq_seller_invites_pending_email",
        "seller_invites",
        ["seller_id", "recipient_email_hash"],
        unique=True,
        postgresql_where=sa.text("accepted_at IS NULL AND revoked_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_seller_invites_pending_email", table_name="seller_invites")
    op.drop_index("ix_seller_invites_expires_at", table_name="seller_invites")
    op.drop_table("seller_invites")
    op.drop_index("ix_seller_memberships_user_active", table_name="seller_memberships")
    op.drop_table("seller_memberships")
    op.drop_index("uq_seller_users_email_lower", table_name="seller_users")
    op.drop_table("seller_users")
