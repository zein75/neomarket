"""Store short-lived, immutable audit export artifacts."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0016_audit_export_artifacts"
down_revision = "0015_snapshot_hash_refs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_export_artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("requested_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("staff_principals.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("high_water_sequence", sa.BigInteger(), nullable=False),
        sa.Column("high_water_hash", sa.String(length=64), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.CheckConstraint("end_at > start_at", name="ck_audit_export_range"),
        sa.CheckConstraint("row_count >= 0", name="ck_audit_export_row_count"),
        sa.CheckConstraint("high_water_sequence >= 0", name="ck_audit_export_high_water_sequence"),
        sa.CheckConstraint("expires_at > created_at", name="ck_audit_export_expiry"),
    )
    op.create_index("ix_audit_export_expiry", "audit_export_artifacts", ["expires_at"])
    op.execute(r"""
CREATE FUNCTION audit_export_reject_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' AND OLD.expires_at <= clock_timestamp() THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION 'audit export artifacts are immutable until expiry';
END $$;
CREATE TRIGGER trg_audit_export_immutable BEFORE UPDATE OR DELETE ON audit_export_artifacts
  FOR EACH ROW EXECUTE FUNCTION audit_export_reject_mutation();
""")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_audit_export_immutable ON audit_export_artifacts")
    op.execute("DROP FUNCTION IF EXISTS audit_export_reject_mutation()")
    op.drop_index("ix_audit_export_expiry", table_name="audit_export_artifacts")
    op.drop_table("audit_export_artifacts")
