"""Track upstream snapshot hashes separately from local content integrity."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0015_snapshot_hash_refs"
down_revision = "0014_audit_integrity_chain"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "moderation_snapshots",
        sa.Column("content_hash", sa.String(length=64), nullable=True),
    )
    op.execute("UPDATE moderation_snapshots SET content_hash = snapshot_hash WHERE content_hash IS NULL")
    op.alter_column("moderation_snapshots", "content_hash", nullable=False)
    op.add_column(
        "moderation_snapshots",
        sa.Column(
            "media_refs",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("moderation_snapshots", "media_refs")
    op.drop_column("moderation_snapshots", "content_hash")
