"""Add optimistic team membership management and immutable audit events."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0051_member_mgmt"
down_revision = "0050_carrier_webhooks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "seller_memberships",
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
    )
    op.create_table(
        "seller_membership_audit",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seller_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("previous_role", sa.String(length=32), nullable=False),
        sa.Column("new_role", sa.String(length=32), nullable=True),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "action IN ('ROLE_CHANGED', 'MEMBERSHIP_REVOKED')",
            name="ck_seller_membership_audit_action",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_seller_membership_audit_seller_time",
        "seller_membership_audit",
        ["seller_id", "occurred_at"],
    )
    op.create_index(
        "ix_seller_membership_audit_target_time",
        "seller_membership_audit",
        ["target_user_id", "occurred_at"],
    )
    op.execute(
        """
        CREATE FUNCTION prevent_seller_membership_audit_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'seller membership audit rows are immutable';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER seller_membership_audit_immutable
        BEFORE UPDATE OR DELETE ON seller_membership_audit
        FOR EACH ROW EXECUTE FUNCTION prevent_seller_membership_audit_mutation();
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER seller_membership_audit_immutable ON seller_membership_audit;"
    )
    op.execute("DROP FUNCTION prevent_seller_membership_audit_mutation();")
    op.drop_index(
        "ix_seller_membership_audit_target_time", table_name="seller_membership_audit"
    )
    op.drop_index(
        "ix_seller_membership_audit_seller_time", table_name="seller_membership_audit"
    )
    op.drop_table("seller_membership_audit")
    op.drop_column("seller_memberships", "revision")
