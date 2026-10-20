"""Persist recoverable pre-create Seller draft autosaves."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0064_seller_draft_autosaves"
down_revision: Union[str, None] = "0063_opaque_seller_sessions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "seller_draft_autosaves",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seller_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("seller_id", "id", name="uq_seller_draft_autosave_owner_key"),
    )
    op.create_index("ix_seller_draft_autosaves_expiry", "seller_draft_autosaves", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_seller_draft_autosaves_expiry", table_name="seller_draft_autosaves")
    op.drop_table("seller_draft_autosaves")
