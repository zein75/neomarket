"""Scope stock adjustment idempotency to seller and persist request outcome."""

from __future__ import annotations

import hashlib
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0029_stock_idempotency"
down_revision: Union[str, None] = "0028_reserved_lte_on_hand"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _request_hash(row: sa.RowMapping) -> str:
    canonical = json.dumps(
        {
            "delta": row["delta"],
            "reason": row["reason"],
            "seller_id": str(row["seller_id"]),
            "sku_id": str(row["sku_id"]),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def upgrade() -> None:
    op.add_column(
        "stock_adjustments", sa.Column("request_hash", sa.String(64), nullable=True)
    )
    op.add_column(
        "stock_adjustments", sa.Column("result_on_hand", sa.Integer(), nullable=True)
    )
    op.add_column(
        "stock_adjustments", sa.Column("result_reserved", sa.Integer(), nullable=True)
    )
    op.drop_constraint(
        "stock_adjustments_idempotency_key_key",
        "stock_adjustments",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_stock_adjustments_seller_key",
        "stock_adjustments",
        ["seller_id", "idempotency_key"],
    )

    # Offline SQL generation cannot select historical rows to backfill their
    # hashes. Those legacy keys remain fail-closed on replay until reconciled.
    if op.get_context().as_sql:
        return

    connection = op.get_bind()
    table = sa.table(
        "stock_adjustments",
        sa.column("adjustment_id"),
        sa.column("sku_id"),
        sa.column("delta"),
        sa.column("reason"),
        sa.column("seller_id"),
        sa.column("idempotency_key"),
        sa.column("request_hash"),
    )
    rows = connection.execute(
        sa.select(
            table.c.adjustment_id,
            table.c.sku_id,
            table.c.delta,
            table.c.reason,
            table.c.seller_id,
        ).where(table.c.idempotency_key.is_not(None))
    ).mappings()
    for row in rows:
        connection.execute(
            table.update()
            .where(table.c.adjustment_id == row["adjustment_id"])
            .values(request_hash=_request_hash(row))
        )


def downgrade() -> None:
    op.drop_constraint(
        "uq_stock_adjustments_seller_key", "stock_adjustments", type_="unique"
    )
    op.create_unique_constraint(
        "stock_adjustments_idempotency_key_key",
        "stock_adjustments",
        ["idempotency_key"],
    )
    op.drop_column("stock_adjustments", "result_reserved")
    op.drop_column("stock_adjustments", "result_on_hand")
    op.drop_column("stock_adjustments", "request_hash")
