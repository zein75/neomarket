"""add moderation pending status

Revision ID: 0002_moderation_pending_status
Revises: 0001_moderation_cards
Create Date: 2026-07-20

"""
from typing import Sequence, Union

from alembic import op


revision: str = "0002_moderation_pending_status"
down_revision: Union[str, None] = "0001_moderation_cards"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE moderationstatus ADD VALUE IF NOT EXISTS 'PENDING'")


def downgrade() -> None:
    pass
