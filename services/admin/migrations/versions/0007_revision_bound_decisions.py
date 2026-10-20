"""Add snapshot-bound moderation leases and durable decision receipts.

Historical moderation rows stay unpinned and are deliberately rejected by the
new decision endpoint until reconciled with an authoritative B2B revision.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0007_revision_bound_decisions"
down_revision = "0006_moderation_outbox_leases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for value in ("DECISION_PENDING", "WAITING_SELLER", "ESCALATED", "STALE", "CANCELLED"):
        op.execute(sa.text(f"ALTER TYPE moderationstatus ADD VALUE IF NOT EXISTS '{value}'"))
    op.create_table(
        "staff_principals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("oidc_issuer", sa.String(length=512), nullable=False),
        sa.Column("oidc_subject", sa.String(length=512), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="ACTIVE", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("oidc_issuer", "oidc_subject", name="uq_staff_issuer_subject"),
    )
    op.create_table(
        "staff_role_grants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("principal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=64), nullable=False),
        sa.Column("scope_key", sa.String(length=255), server_default="global", nullable=False),
        sa.Column("granted_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["principal_id"], ["staff_principals.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("principal_id", "role", "scope_key", name="uq_staff_role_scope"),
    )
    op.create_index("ix_staff_grants_principal_expiry", "staff_role_grants", ["principal_id", "expires_at"])
    op.add_column("moderation_cards", sa.Column("submitted_revision", sa.Integer(), nullable=True))
    op.add_column("moderation_cards", sa.Column("snapshot_hash", sa.String(length=64), nullable=True))
    op.add_column("moderation_cards", sa.Column("version", sa.Integer(), server_default="1", nullable=False))
    op.add_column("moderation_cards", sa.Column("lease_token_hash", sa.String(length=64), nullable=True))
    op.add_column("moderation_cards", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("moderation_cards", sa.Column("fencing_version", sa.Integer(), server_default="0", nullable=False))
    op.create_check_constraint(
        "ck_moderation_card_revision_positive",
        "moderation_cards",
        "submitted_revision IS NULL OR submitted_revision >= 1",
    )
    op.create_check_constraint("ck_moderation_card_version_positive", "moderation_cards", "version >= 1")
    op.create_check_constraint("ck_moderation_card_fencing_nonnegative", "moderation_cards", "fencing_version >= 0")
    op.create_index(
        "ix_moderation_cards_queue_keyset",
        "moderation_cards",
        ["status", "queue_priority", "created_at", "id"],
    )
    op.create_table(
        "moderation_decision_receipts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("ticket_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("result_status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["ticket_id"], ["moderation_cards.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("actor_id", "idempotency_key", name="uq_moderation_decision_actor_key"),
    )
    op.create_index("ix_moderation_decision_receipts_ticket", "moderation_decision_receipts", ["ticket_id", "created_at"])
    op.create_unique_constraint(
        "uq_moderation_product_revision_kind",
        "moderation_cards",
        ["product_id", "submitted_revision", "kind"],
    )
    op.create_table(
        "moderation_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("ticket_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["ticket_id"], ["moderation_cards.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("ticket_id", "revision", name="uq_moderation_snapshot_ticket_revision"),
    )
    op.create_table(
        "moderation_claim_receipts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("ticket_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("operation", sa.String(length=16), server_default="CLAIM", nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("fencing_version", sa.Integer(), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["ticket_id"], ["moderation_cards.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("actor_id", "idempotency_key", name="uq_moderation_claim_actor_key"),
    )


def downgrade() -> None:
    op.drop_index("ix_staff_grants_principal_expiry", table_name="staff_role_grants")
    op.drop_table("staff_role_grants")
    op.drop_table("staff_principals")
    op.drop_table("moderation_claim_receipts")
    op.drop_table("moderation_snapshots")
    op.drop_constraint("uq_moderation_product_revision_kind", "moderation_cards", type_="unique")
    op.drop_index("ix_moderation_decision_receipts_ticket", table_name="moderation_decision_receipts")
    op.drop_table("moderation_decision_receipts")
    op.drop_index("ix_moderation_cards_queue_keyset", table_name="moderation_cards")
    op.drop_constraint("ck_moderation_card_fencing_nonnegative", "moderation_cards", type_="check")
    op.drop_constraint("ck_moderation_card_version_positive", "moderation_cards", type_="check")
    op.drop_constraint("ck_moderation_card_revision_positive", "moderation_cards", type_="check")
    op.drop_column("moderation_cards", "fencing_version")
    op.drop_column("moderation_cards", "lease_expires_at")
    op.drop_column("moderation_cards", "lease_token_hash")
    op.drop_column("moderation_cards", "version")
    op.drop_column("moderation_cards", "snapshot_hash")
    op.drop_column("moderation_cards", "submitted_revision")
