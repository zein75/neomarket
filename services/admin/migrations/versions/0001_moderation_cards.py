"""moderation cards

Revision ID: 0001_moderation_cards
Revises:
Create Date: 2026-07-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0001_moderation_cards"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    status_enum = postgresql.ENUM(
        "CREATED",
        "IN_REVIEW",
        "MODERATED",
        "BLOCKED",
        "HARD_BLOCKED",
        "EDITED",
        name="moderationstatus",
        create_type=False,
    )
    status_enum.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "moderation_cards",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("seller_id", sa.UUID(), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=False, server_default="PRODUCT"),
        sa.Column("queue_priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("moderator_id", sa.UUID(), nullable=True),
        sa.Column("status", status_enum, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "moderation_skus",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("card_id", sa.UUID(), nullable=False),
        sa.Column("sku_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["card_id"], ["moderation_cards.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("moderation_skus")
    op.drop_table("moderation_cards")
    sa.Enum(name="moderationstatus").drop(op.get_bind(), checkfirst=True)
