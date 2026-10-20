"""Persist structured request and actor context in the immutable audit chain."""

from alembic import op
import sqlalchemy as sa


revision = "0024_structured_audit_context"
down_revision = "0023_moderation_decision_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column("audit_logs", sa.Column("request_id", sa.String(length=128), nullable=True))
    op.add_column("audit_logs", sa.Column("correlation_id", sa.String(length=128), nullable=True))
    op.add_column("audit_logs", sa.Column("actor_roles", sa.JSON(), nullable=True))
    op.add_column("audit_logs", sa.Column("before_hash", sa.String(length=64), nullable=True))
    op.add_column("audit_logs", sa.Column("after_hash", sa.String(length=64), nullable=True))
    op.add_column("audit_logs", sa.Column("reason_code", sa.String(length=64), nullable=True))
    # Existing immutable records retain v1 hashes. New records use v2, which
    # covers the additional context fields without rewriting historical hashes.
    op.add_column(
        "audit_logs",
        sa.Column("integrity_version", sa.SmallInteger(), nullable=False, server_default=sa.text("1")),
    )
    op.create_check_constraint(
        "ck_audit_logs_integrity_version",
        "audit_logs",
        "integrity_version IN (1, 2)",
    )
    op.create_check_constraint(
        "ck_audit_logs_v2_actor_roles_present",
        "audit_logs",
        "integrity_version = 1 OR actor_roles IS NOT NULL",
    )
    op.create_check_constraint(
        "ck_audit_logs_actor_roles_array",
        "audit_logs",
        "actor_roles IS NULL OR jsonb_typeof(actor_roles::jsonb) = 'array'",
    )
    op.create_check_constraint(
        "ck_audit_logs_before_hash_format",
        "audit_logs",
        "before_hash IS NULL OR before_hash ~ '^[A-Fa-f0-9]{64}$'",
    )
    op.create_check_constraint(
        "ck_audit_logs_after_hash_format",
        "audit_logs",
        "after_hash IS NULL OR after_hash ~ '^[A-Fa-f0-9]{64}$'",
    )
    op.alter_column(
        "audit_logs",
        "integrity_version",
        existing_type=sa.SmallInteger(),
        server_default=sa.text("2"),
    )
    op.create_index("ix_audit_logs_request_id", "audit_logs", ["request_id"])

    op.execute(r"""
CREATE OR REPLACE FUNCTION audit_log_chain_append() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    previous_sequence bigint;
    previous_hash text;
    event_payload jsonb;
BEGIN
    SELECT last_sequence,last_hash INTO previous_sequence,previous_hash
      FROM audit_chain_heads WHERE id=1 FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'audit chain head is missing'; END IF;
    NEW.sequence_no := previous_sequence + 1;
    NEW.previous_hash := previous_hash;

    IF NEW.integrity_version = 1 THEN
        event_payload := jsonb_build_object(
            'id',NEW.id,'actor_id',NEW.actor_id,'action',NEW.action,
            'entity_type',NEW.entity_type,'entity_id',NEW.entity_id,
            'details',NEW.details::jsonb,'created_at',NEW.created_at
        );
    ELSIF NEW.integrity_version = 2 THEN
        NEW.actor_roles := COALESCE(NEW.actor_roles, '[]'::json);
        event_payload := jsonb_build_object(
            'id',NEW.id,'actor_id',NEW.actor_id,'action',NEW.action,
            'entity_type',NEW.entity_type,'entity_id',NEW.entity_id,
            'details',NEW.details::jsonb,'created_at',NEW.created_at
        ) || jsonb_build_object(
            'integrity_version',NEW.integrity_version,
            'request_id',NEW.request_id,
            'correlation_id',NEW.correlation_id,
            'actor_roles',NEW.actor_roles::jsonb,
            'before_hash',NEW.before_hash,
            'after_hash',NEW.after_hash,
            'reason_code',NEW.reason_code
        );
    ELSE
        RAISE EXCEPTION 'unsupported audit integrity version %', NEW.integrity_version;
    END IF;

    NEW.integrity_hash := encode(
        digest(convert_to(previous_hash || event_payload::text,'UTF8'),'sha256'),
        'hex'
    );
    UPDATE audit_chain_heads
       SET last_sequence=NEW.sequence_no,last_hash=NEW.integrity_hash
     WHERE id=1;
    RETURN NEW;
END $$;
""")


def downgrade() -> None:
    # Removing v2 metadata would make immutable v2 events unverifiable.
    raise RuntimeError("audit context migration is irreversible; roll forward to preserve the hash chain")
