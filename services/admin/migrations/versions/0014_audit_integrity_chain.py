"""Make audit events append-only and link them with a serialized SHA-256 chain."""

from alembic import op
import sqlalchemy as sa


revision = "0014_audit_integrity_chain"
down_revision = "0013_admin_session_revocation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.create_table(
        "audit_chain_heads",
        sa.Column("id", sa.SmallInteger(), primary_key=True),
        sa.Column("last_sequence", sa.BigInteger(), nullable=False),
        sa.Column("last_hash", sa.String(length=64), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_audit_chain_single_head"),
    )
    op.add_column("audit_logs", sa.Column("sequence_no", sa.BigInteger(), nullable=True))
    op.add_column("audit_logs", sa.Column("previous_hash", sa.String(length=64), nullable=True))
    op.add_column("audit_logs", sa.Column("integrity_hash", sa.String(length=64), nullable=True))
    op.execute("LOCK TABLE audit_logs IN ACCESS EXCLUSIVE MODE")
    op.execute("INSERT INTO audit_chain_heads (id,last_sequence,last_hash) VALUES (1,0,repeat('0',64))")
    op.execute(r"""
DO $$
DECLARE
    event_row record;
    next_hash text;
    chain_hash text := repeat('0',64);
    next_sequence bigint := 0;
BEGIN
    FOR event_row IN SELECT * FROM audit_logs ORDER BY created_at,id LOOP
        next_sequence := next_sequence + 1;
        next_hash := encode(digest(convert_to(chain_hash || jsonb_build_object(
            'id',event_row.id,'actor_id',event_row.actor_id,'action',event_row.action,
            'entity_type',event_row.entity_type,'entity_id',event_row.entity_id,
            'details',event_row.details::jsonb,'created_at',event_row.created_at
        )::text,'UTF8'),'sha256'),'hex');
        UPDATE audit_logs SET sequence_no=next_sequence,previous_hash=chain_hash,integrity_hash=next_hash
          WHERE id=event_row.id;
        chain_hash := next_hash;
    END LOOP;
    UPDATE audit_chain_heads SET last_sequence=next_sequence,last_hash=chain_hash WHERE id=1;
END $$;
""")
    op.alter_column("audit_logs", "sequence_no", nullable=False)
    op.alter_column("audit_logs", "previous_hash", nullable=False)
    op.alter_column("audit_logs", "integrity_hash", nullable=False)
    op.create_unique_constraint("uq_audit_logs_sequence_no", "audit_logs", ["sequence_no"])
    op.create_unique_constraint("uq_audit_logs_integrity_hash", "audit_logs", ["integrity_hash"])
    op.execute(r"""
CREATE FUNCTION audit_log_chain_append() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    previous_sequence bigint;
    previous_hash text;
BEGIN
    SELECT last_sequence,last_hash INTO previous_sequence,previous_hash
      FROM audit_chain_heads WHERE id=1 FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'audit chain head is missing'; END IF;
    NEW.sequence_no := previous_sequence + 1;
    NEW.previous_hash := previous_hash;
    NEW.integrity_hash := encode(digest(convert_to(previous_hash || jsonb_build_object(
        'id',NEW.id,'actor_id',NEW.actor_id,'action',NEW.action,
        'entity_type',NEW.entity_type,'entity_id',NEW.entity_id,
        'details',NEW.details::jsonb,'created_at',NEW.created_at
    )::text,'UTF8'),'sha256'),'hex');
    UPDATE audit_chain_heads SET last_sequence=NEW.sequence_no,last_hash=NEW.integrity_hash WHERE id=1;
    RETURN NEW;
END $$;
CREATE TRIGGER trg_audit_log_chain_append BEFORE INSERT ON audit_logs
  FOR EACH ROW EXECUTE FUNCTION audit_log_chain_append();

CREATE FUNCTION audit_log_reject_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit logs are append-only';
END $$;
CREATE TRIGGER trg_audit_logs_append_only BEFORE UPDATE OR DELETE ON audit_logs
  FOR EACH ROW EXECUTE FUNCTION audit_log_reject_mutation();

CREATE FUNCTION audit_chain_head_reject_direct_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF pg_trigger_depth() < 2 THEN RAISE EXCEPTION 'audit chain head is maintained by audit inserts'; END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER trg_audit_chain_head_guard BEFORE UPDATE OR DELETE ON audit_chain_heads
  FOR EACH ROW EXECUTE FUNCTION audit_chain_head_reject_direct_update();
""")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_audit_chain_head_guard ON audit_chain_heads")
    op.execute("DROP FUNCTION IF EXISTS audit_chain_head_reject_direct_update()")
    op.execute("DROP TRIGGER IF EXISTS trg_audit_logs_append_only ON audit_logs")
    op.execute("DROP FUNCTION IF EXISTS audit_log_reject_mutation()")
    op.execute("DROP TRIGGER IF EXISTS trg_audit_log_chain_append ON audit_logs")
    op.execute("DROP FUNCTION IF EXISTS audit_log_chain_append()")
    op.drop_constraint("uq_audit_logs_integrity_hash", "audit_logs", type_="unique")
    op.drop_constraint("uq_audit_logs_sequence_no", "audit_logs", type_="unique")
    op.drop_column("audit_logs", "integrity_hash")
    op.drop_column("audit_logs", "previous_hash")
    op.drop_column("audit_logs", "sequence_no")
    op.drop_table("audit_chain_heads")
