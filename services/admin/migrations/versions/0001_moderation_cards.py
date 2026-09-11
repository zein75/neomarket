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
        "blocking_reasons",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("hard_block", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
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
        sa.UniqueConstraint("code"),
    )
    blocking_reasons = sa.table(
        "blocking_reasons",
        sa.column("id", sa.UUID()),
        sa.column("code", sa.String()),
        sa.column("title", sa.String()),
        sa.column("description", sa.Text()),
        sa.column("hard_block", sa.Boolean()),
        sa.column("is_active", sa.Boolean()),
    )
    op.bulk_insert(
        blocking_reasons,
        [
            {
                "id": "a7b8c9d0-1234-5678-ef01-890123456789",
                "code": "DESCRIPTION_MISMATCH",
                "title": "Описание не соответствует товару",
                "description": None,
                "hard_block": False,
                "is_active": True,
            },
            {
                "id": "b8c9d0e1-2345-6789-f012-901234567890",
                "code": "IMAGE_MISMATCH",
                "title": "Изображение не соответствует товару",
                "description": None,
                "hard_block": False,
                "is_active": True,
            },
            {
                "id": "c9d0e1f2-3456-7890-0123-012345678901",
                "code": "INVALID_CATEGORY",
                "title": "Некорректная категория товара",
                "description": None,
                "hard_block": False,
                "is_active": True,
            },
            {
                "id": "d0e1f2a3-4567-8901-1234-123456789012",
                "code": "INSUFFICIENT_INFORMATION",
                "title": "Недостаточно информации о товаре",
                "description": None,
                "hard_block": False,
                "is_active": True,
            },
            {
                "id": "e1f2a3b4-5678-9012-2345-234567890123",
                "code": "OFFENSIVE_MATERIALS",
                "title": "Нецензурные или оскорбительные материалы",
                "description": None,
                "hard_block": False,
                "is_active": True,
            },
            {
                "id": "f2a3b4c5-6789-0123-3456-345678901234",
                "code": "DUPLICATE_PRODUCT",
                "title": "Дублирование существующего товара",
                "description": None,
                "hard_block": False,
                "is_active": True,
            },
            {
                "id": "a3b4c5d6-7890-1234-4567-456789012345",
                "code": "INVALID_PRICE",
                "title": "Некорректная цена",
                "description": None,
                "hard_block": False,
                "is_active": True,
            },
            {
                "id": "b4c5d6e7-8901-2345-5678-567890123456",
                "code": "COUNTERFEIT_PRODUCT",
                "title": "Контрафактный товар",
                "description": None,
                "hard_block": True,
                "is_active": True,
            },
            {
                "id": "c5d6e7f8-9012-3456-6789-678901234567",
                "code": "FORBIDDEN_GOODS",
                "title": "Товар запрещён к продаже на территории РФ",
                "description": None,
                "hard_block": True,
                "is_active": True,
            },
            {
                "id": "d6e7f8a9-0123-4567-7890-789012345678",
                "code": "COPYRIGHT_VIOLATION",
                "title": "Товар нарушает авторские права",
                "description": None,
                "hard_block": True,
                "is_active": True,
            },
        ],
    )
    op.create_table(
        "moderation_cards",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("seller_id", sa.UUID(), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=False, server_default="CREATE"),
        sa.Column("queue_priority", sa.Integer(), nullable=False, server_default="3"),
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
    op.drop_table("blocking_reasons")
    sa.Enum(name="moderationstatus").drop(op.get_bind(), checkfirst=True)
