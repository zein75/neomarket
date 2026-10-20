"""Persist immutable moderation decision evidence as structured columns."""

from alembic import op
import sqlalchemy as sa


revision = "0023_moderation_decision_evidence"
down_revision = "0022_admin_keyset_page_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    # Alembic's default version_num is VARCHAR(32), but this revision ID is
    # longer. Widen before Alembic records this head or every clean upgrade
    # fails after applying the migration body.
    op.alter_column(
        "alembic_version",
        "version_num",
        existing_type=sa.String(length=32),
        type_=sa.String(length=128),
        existing_nullable=False,
    )
    op.add_column(
        "moderation_snapshots",
        sa.Column("policy_version", sa.Integer(), nullable=True),
    )
    op.add_column(
        "moderation_decision_receipts",
        sa.Column("product_revision", sa.Integer(), nullable=True),
    )
    op.add_column(
        "moderation_decision_receipts",
        sa.Column("snapshot_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "moderation_decision_receipts",
        sa.Column("policy_version", sa.Integer(), nullable=True),
    )
    op.add_column(
        "moderation_decision_receipts",
        sa.Column("reason_codes", sa.JSON(), nullable=True),
    )
    op.add_column(
        "moderation_decision_receipts",
        sa.Column("field_reports", sa.JSON(), nullable=True),
    )
    op.add_column(
        "moderation_decision_receipts",
        sa.Column("comment", sa.Text(), nullable=True),
    )

    # Backfill only evidence already present in immutable snapshot/audit/outbox
    # records. Historical rows without source evidence remain explicitly NULL.
    op.execute("""
        UPDATE moderation_snapshots
           SET policy_version = (content->>'policy_version')::integer
         WHERE policy_version IS NULL
           AND content->>'policy_version' ~ '^[1-9][0-9]{0,8}$'
    """)
    op.execute("""
        UPDATE moderation_decision_receipts AS decision
           SET product_revision = CASE
                   WHEN audit.details->>'product_revision' ~ '^[1-9][0-9]{0,8}$'
                   THEN (audit.details->>'product_revision')::integer
                   ELSE NULL END,
               snapshot_hash = CASE
                   WHEN audit.details->>'snapshot_hash' ~ '^[a-fA-F0-9]{64}$'
                   THEN lower(audit.details->>'snapshot_hash')
                   ELSE NULL END,
               policy_version = CASE
                   WHEN audit.details->>'policy_version' ~ '^[1-9][0-9]{0,8}$'
                   THEN (audit.details->>'policy_version')::integer
                   ELSE NULL END,
               reason_codes = audit.details->'reason_codes'
          FROM audit_logs AS audit
         WHERE audit.entity_type = 'moderation_ticket'
           AND audit.action LIKE 'TICKET_DECISION_%'
           AND audit.details->>'decision_id' = decision.id::text
    """)
    op.execute("""
        UPDATE moderation_decision_receipts AS decision
           SET field_reports = outbox.payload->'field_reports'
          FROM moderation_outbox_events AS outbox
         WHERE outbox.id = decision.id
           AND outbox.event_type = 'MODERATION_DECISION'
           AND outbox.payload->'field_reports' IS NOT NULL
    """)
    op.execute("""
        CREATE FUNCTION reject_admin_immutable_row_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'immutable Admin evidence rows cannot be updated or deleted';
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER trg_moderation_snapshots_immutable
        BEFORE UPDATE OR DELETE ON moderation_snapshots
        FOR EACH ROW EXECUTE FUNCTION reject_admin_immutable_row_mutation()
    """)
    op.execute("""
        CREATE TRIGGER trg_moderation_decision_receipts_immutable
        BEFORE UPDATE OR DELETE ON moderation_decision_receipts
        FOR EACH ROW EXECUTE FUNCTION reject_admin_immutable_row_mutation()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_moderation_decision_receipts_immutable ON moderation_decision_receipts")
    op.execute("DROP TRIGGER trg_moderation_snapshots_immutable ON moderation_snapshots")
    op.execute("DROP FUNCTION reject_admin_immutable_row_mutation()")
    op.drop_column("moderation_decision_receipts", "comment")
    op.drop_column("moderation_decision_receipts", "field_reports")
    op.drop_column("moderation_decision_receipts", "reason_codes")
    op.drop_column("moderation_decision_receipts", "policy_version")
    op.drop_column("moderation_decision_receipts", "snapshot_hash")
    op.drop_column("moderation_decision_receipts", "product_revision")
    op.drop_column("moderation_snapshots", "policy_version")
